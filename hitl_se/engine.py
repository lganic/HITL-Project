from __future__ import annotations

import copy
import difflib
import time

from .step_timing import record_step

from .agents import CATALOG, search_catalog
from .policy import ToolBroker, inspect_policy, scope_for_testing
from .util import WorkflowError, digest, validate_files
from .workflows import GATES, STATES, TEST_STAGES

GATE_REFS = {
    "req.clarify": ["collected"], "req.check": ["collected", "model"],
    "design.direction": ["srs", "design_options", "design_refined", "design_search", "design_observations"],
    "design.decision": ["srs", "design_refined", "design_observations"],
    "dev.plan_review": ["srs", "adr", "main", "plan_a", "plan_b"],
    "dev.final": ["candidate_a", "candidate_b", "evidence_a", "evidence_b", "candidate_diff", "review_a", "review_b"],
    "test.plan_review": ["test_context", "test_plan", "test_action", "test_result", "test_summary"],
    "test.policy": ["test_plan", "test_bundle", "test_action"],
    "test.verify": ["test_plan", "test_bundle", "test_result", "test_summary", "test_completion"],
    "deploy.manual": ["main", "test_signoff", "deployment_help"],
    "review.feedback": ["main", "review_pack", "deployment_record"],
}


class Engine:
    def __init__(self, store, agents, runner, lease_seconds=600):
        self.store, self.agents, self.runner = store, agents, runner
        self.broker = ToolBroker(store, runner)
        self.lease_seconds = lease_seconds

    def ref(self, identifier):
        art = self.store.artifact(identifier)
        return {"artifact_id": identifier, "kind": art["kind"], "hash": art["hash"], "content": art["payload"]}

    def payload(self, p, key):
        return self.store.artifact(p["data"][key])["payload"]

    def common(self, p, *keys):
        d = p["data"]
        context = {"task": d["seed"], "iteration": p["iteration"], "human_feedback": d["feedback"][-12:]}
        for key in keys:
            if key in d:
                context[key] = self.ref(d[key])
        return context

    def dev_scope(self, p, next_round=False):
        d = p["data"]
        return {"kind": "development_evaluation", "baseline": d.get("dev_base", d["main"]), "plan_a": d["plan_a"], "plan_b": d["plan_b"], "round": d["dev_round"] + int(next_round), "tool": "python_checks", "runner": self.runner.fingerprint()}

    def gate_proposal(self, p):
        d, state = p["data"], p["state"]
        spec = GATES[state]
        refs = [self.ref(d[k]) for k in GATE_REFS[state] if isinstance(d.get(k), str)]
        risks = [risk for r in refs for risk in r["content"].get("risks", [])]
        web_files = sorted({name for r in refs for name in r["content"].get("files", {})
                            if name.endswith((".html", ".css", ".js", ".mjs", ".svg"))})
        if web_files:
            risks.append("Python checks do not parse or run these web files: " + ", ".join(web_files)
                         + ". Inspect them and test browser behavior before accepting.")
        proposals = {
            "req.clarify": "Answer the Collector's open questions before requirements modeling.",
            "req.check": "Accept this exact requirements model as the structured SRS input.",
            "design.direction": "Select or correct the architectural direction for refinement.",
            "design.decision": "Select the refined architecture to record in an accepted ADR.",
            "dev.plan_review": "Choose/correct the approach before commissioning two independent implementations and bounded checks.",
            "dev.final": "Choose a passing implementation for the canonical source merge, or request corrections.",
            "test.plan_review": "Review the test objective, assumptions, constraints, added test files and intervention signals.",
            "test.verify": "Verify the measured evidence and decide whether testing is truly complete.",
            "deploy.manual": "Record a deployment you performed manually, or explicitly defer it.",
            "review.feedback": "Record the demonstration and stakeholder feedback, then start new requirements or close the iteration.",
        }
        proposal = {"title": spec.title, "state": state, "source_requirement": spec.requirement,
                    "proposal": proposals.get(state, "Review the exact proposed action."),
                    "rationale": "This decision belongs to the human; agent recommendations are advisory.",
                    "agent_rationales": [{"artifact_id": r["artifact_id"], "rationale": r["content"]["rationale"]} for r in refs if "rationale" in r["content"]],
                    "artifacts": refs, "risks": risks or ["Agent outputs and tests can omit important cases; inspect the evidence."],
                    "alternatives": ["approve the exact proposal", "reject and revisit the earlier stage", "modify with corrective feedback", "request more information without advancing"],
                    "actions": ["approve", "reject", "modify", "info"],
                    "routes": {"approve": spec.approve, "reject": spec.reject, "modify": spec.modify},
                    "human_feedback": d["feedback"][-3:], "required_input": "Explain your decision in feedback."}
        if state == "req.clarify":
            proposal["required_input"] = "Answer the Collector's questions in feedback."
        if state in {"design.direction", "design.decision"}:
            key = "design_refined" if d.get("direction_refined") or state == "design.decision" else "design_options"
            proposal["selection_options"] = [o["id"] for o in self.payload(p, key)["options"]]
            proposal["required_input"] = 'Approve with payload {"selection":"option ID"}; supply your rationale in feedback.'
        if state in {"dev.plan_review", "dev.final"}:
            proposal["execution_scope"] = self.dev_scope(p, next_round=state == "dev.final")
            proposal["evaluation_policy"] = inspect_policy("python_checks")
            proposal["evaluation_permission"] = "For plan approval or final modify only: run this fixed recipe on both generated candidates in the displayed sandbox, with no network or host execution."
            proposal["selection_options"] = ["A", "B", "custom"] if state == "dev.plan_review" else ["A", "B"]
            proposal["required_input"] = ('Approve with {"selection":"A|B|custom", "allow_evaluation":true}; custom also requires "approach".' if state == "dev.plan_review" else 'Approve with {"selection":"A|B"}. Modify requires {"allow_evaluation":true} and correction feedback. Reject returns to planning.')
        if state == "test.plan_review":
            proposal["interventions"] = d.get("interventions", [])
            proposal["runner"] = self.runner.fingerprint()
        if state == "test.policy":
            action = self.payload(p, "test_action")
            proposal.update(execution_scope=action["scope"], policy=action["policy"], proposal=action["proposal"]["summary"], rationale=action["proposal"]["rationale"])
            proposal["required_input"] = "Approve only the exact tool, code bundle and sandbox scope shown; a policy denial cannot be overridden."
        if state == "test.verify":
            proposal["test_evidence"] = [self.ref(x) for x in d.get("test_evidence", [])]
            proposal["measured_checks_pass"] = self.has_passing_evidence(p)
        if state == "deploy.manual":
            proposal["required_input"] = 'After your manual action, use {"status":"deployed|deferred", "record":"what YOU did, or why deferred"}. This app does not deploy.'
        if state == "review.feedback":
            proposal["required_input"] = 'Record real demo/stakeholder notes in "demo_notes"; use "new_requirements":"..." to start another iteration, or "close":true.'
        return proposal

    def step(self, project):
        p = self.store.project(project)
        if p["state"] == "review.closed":
            return {"status": "complete", "state": p["state"]}
        if p["status"] == "waiting":
            return {"status": "waiting", "gate": self.store.pending(project)}
        if p["status"] != "ready":
            raise WorkflowError(f"Project is {p['status']}: {p['error'] or 'another worker may be active'}")
        if p["state"] in GATES:
            return {"status": "waiting", "gate": self.store.open_gate(p, self.gate_proposal(p))}
        p = self.store.claim(project, self.lease_seconds)
        # Time automated work only; human waiting is intentionally excluded.
        started_ns = time.perf_counter_ns()
        next_state = ""
        step_status = "failed"
        try:
            next_state, data, outputs = self.advance(p)
            if next_state not in STATES:
                raise WorkflowError("Internal transition targets an unknown state")
            self.store.finish(p, next_state, data, outputs)
            step_status = "success"
        except Exception as exc:
            message = str(exc) if isinstance(exc, WorkflowError) else f"{type(exc).__name__} during {p['state']}; inspect local code and retry"
            self.store.fail(p, message)
            raise WorkflowError(message) from exc
        finally:
            elapsed_ns = time.perf_counter_ns() - started_ns
            try:
                record_step(p["state"], next_state, elapsed_ns, step_status)
            except OSError as logging_error:
                print(f"Warning: could not save step timing: {logging_error}")
        return {"status": "ready", "state": next_state}

    def run(self, project, max_steps=80, on_step=None):
        for _ in range(max_steps):
            if on_step:
                on_step(self.store.project(project)["state"])
            result = self.step(project)
            if result["status"] in {"waiting", "complete"}:
                return result
        raise WorkflowError("Step budget reached; inspect and explicitly continue")

    def advance(self, p):
        d, state = copy.deepcopy(p["data"]), p["state"]
        outputs = {}
        def emit(key, value, producer="engine", kind=None):
            outputs[key] = (kind or key, value, producer)
            d[key] = "@out:" + key
            return value
        def agent(key, role, context):
            return emit(key, self.agents.run(role, context), role)
        def done(next_state):
            return next_state, d, outputs

        if state == "req.collect":
            result = agent("collected", "collector", self.common(p, "previous_srs"))
            return done("req.clarify" if result["questions"] else "req.model")
        if state == "req.model":
            agent("model", "modeler", self.common(p, "collected", "previous_srs"))
            return done("req.check")
        if state == "req.document":
            approved = self.payload(p, "model")
            prose = agent("srs_prose", "documenter", self.common(p, "model"))
            emit("srs", {"schema_version": 1, "project": p["name"], "iteration": p["iteration"], "approval": d["requirements_decision"], "approved_model": d["model"], "overview": prose["overview"], "glossary": prose["glossary"], **{k: approved[k] for k in ("requirements", "entities", "relationships", "constraints", "assumptions")}})
            return done("design.explore")
        if state == "design.explore":
            ctx = self.common(p, "srs")
            search = agent("design_search", "design_search", {**ctx, "catalog": CATALOG})
            observations = search_catalog(search["queries"])
            emit("design_observations", {"observations": observations, "catalog_version": 1})
            agent("design_options", "architect", {**ctx, "queries": search["queries"], "criteria": search["criteria"], "observations": observations})
            d.pop("design_refined", None)
            d["direction_refined"] = False
            return done("design.direction")
        if state == "design.refine":
            ctx = self.common(p, "srs", "design_options", "design_refined", "design_observations")
            ctx["human_direction"] = d.get("design_direction", {})
            agent("design_refined", "refiner", ctx)
            if d.pop("design_feedback_loop", False):
                d["direction_refined"] = True
                return done("design.direction")
            return done("design.decision")
        if state == "design.record":
            refined = self.payload(p, "design_refined")
            selected = next(o for o in refined["options"] if o["id"] == d["design_choice"])
            emit("adr", {"status": "accepted_by_human", "decision": selected, "human_rationale": d["design_reason"], "alternatives": [o for o in refined["options"] if o["id"] != d["design_choice"]], "srs": d["srs"], "refinement": d["design_refined"], "approval": d["architecture_decision"]})
            return done("dev.plan_a")
        if state in {"dev.plan_a", "dev.plan_b"}:
            side = state[-1]
            if side == "a":
                d["dev_base"] = d["main"]
                for key in ("plan_a", "plan_b", "candidate_a", "candidate_b", "evidence_a", "evidence_b", "review_a", "review_b", "candidate_diff"):
                    d.pop(key, None)
            # No sibling plan is in either context.
            ctx = self.common(p, "srs", "adr", "main")
            agent("plan_" + side, "planner_" + side, ctx)
            return done("dev.plan_b" if side == "a" else "dev.plan_review")
        if state in {"dev.implement_a", "dev.implement_b"}:
            side = state[-1]
            ctx = self.common(p, "srs", "adr", "dev_base", "plan_" + side)
            ctx["approved_approach"] = d["approved_approach"]
            ctx["locked_acceptance_tests"] = d["dev_tests"]
            if "candidate_" + side in d:
                ctx["own_previous_candidate"] = self.ref(d["candidate_" + side])
            result = self.agents.run("implementer_" + side, ctx)
            files = dict(self.payload(p, "dev_base")["files"])
            files.update(result["files"])
            files.update(d["dev_tests"])
            validate_files(files)
            emit("candidate_" + side, {**result, "files": files, "base": d["dev_base"], "round": d["dev_round"], "approved_approach": d["approved_approach"]}, "implementer_" + side)
            return done("dev.implement_b" if side == "a" else "dev.evaluate")
        if state == "dev.evaluate":
            if d["eval_scope"]["runner"] != self.runner.fingerprint():
                d["feedback"].append({"state": state, "action": "environment_changed", "text": "Review the changed sandbox before evaluating candidates."})
                return done("dev.plan_review")
            a, b = self.payload(p, "candidate_a"), self.payload(p, "candidate_b")
            for side, candidate in (("a", a), ("b", b)):
                if candidate["base"] != d["dev_base"] or candidate["round"] != d["dev_round"]:
                    raise WorkflowError("Candidate does not match the authorized development round")
                evidence = self.broker.execute(p, d["evaluation_decision"], d["eval_scope"], side, candidate["files"], "python_checks")
                emit("evidence_" + side, {**evidence, "candidate": d["candidate_" + side]}, "runner")
            diff = []
            for name in sorted(a["files"].keys() | b["files"].keys()):
                diff.extend(difflib.unified_diff(a["files"].get(name, "").splitlines(True), b["files"].get(name, "").splitlines(True), fromfile="A/" + name, tofile="B/" + name))
            emit("candidate_diff", {"diff": "".join(diff), "identical_source": a["files"] == b["files"]})
            return done("dev.review_a")
        if state in {"dev.review_a", "dev.review_b"}:
            side = state[-1]
            ctx = self.common(p, "srs", "adr", "candidate_a", "candidate_b", "evidence_a", "evidence_b", "candidate_diff")
            agent("review_" + side, "reviewer_" + side, ctx)
            return done("dev.review_b" if side == "a" else "dev.final")
        if state == "dev.merge":
            candidate = self.payload(p, "candidate_" + d["selected_candidate"].lower())
            evidence = self.payload(p, "evidence_" + d["selected_candidate"].lower())
            if d["main"] != candidate["base"] or not self.evidence_passes(evidence) or evidence["tree_hash"] != digest(candidate["files"]):
                raise WorkflowError("Merge refused: baseline or passing candidate evidence changed")
            emit("main", {"files": candidate["files"], "parent": d["main"], "candidate": d["candidate_" + d["selected_candidate"].lower()], "approval": d["merge_decision"], "iteration": p["iteration"]})
            return done("test.context")
        if state == "test.context":
            emit("test_context", {"main": self.ref(d["main"]), "srs": self.ref(d["srs"]), "adr": self.ref(d["adr"]), "environment": self.runner.fingerprint(), "stage": 1})
            d["test_evidence"] = []
            return done("test.prepare")
        if state == "test.prepare":
            plan = agent("test_plan", "test_planner", self.common(p, "test_context", "main", "srs"))
            files = dict(self.payload(p, "main")["files"])
            if set(files) & set(plan["test_files"]):
                raise WorkflowError("Independent test additions may not overwrite existing files")
            files.update(plan["test_files"])
            validate_files(files)
            emit("test_bundle", {"files": files, "main": d["main"]})
            d.update(test_evidence=[], failure_count=0, test_review_mode="plan", interventions=[])
            for key in ("test_action", "test_result", "test_summary", "test_completion"):
                d.pop(key, None)
            return done("test.plan_review")
        if state == "test.propose":
            result = self.agents.run("test_proposer", {**self.common(p, "test_plan", "test_bundle", "test_result", "test_summary"), "allowed_recipes": ["static_analysis", "python_tests", "python_checks"]})
            bundle = self.store.artifact(d["test_bundle"])
            scope = scope_for_testing(bundle["id"], bundle["hash"], result["tool"], self.runner.fingerprint())
            signals = []
            if result["confidence"] < .70:
                signals.append("low confidence")
            if result["strategy_changed"]:
                signals.append("major strategy change")
            if result["environment_changed"] or d.get("test_environment") != self.runner.fingerprint():
                signals.append("environment/toolchain change")
            emit("test_action", {"proposal": result, "scope": scope, "policy": inspect_policy(result["tool"]), "interventions": signals}, "test_proposer")
            d.update(interventions=signals, test_review_mode="action")
            return done("test.plan_review" if signals else "test.policy")
        if state == "test.execute":
            action = self.payload(p, "test_action")
            bundle = self.store.artifact(d["test_bundle"])
            if action["scope"]["runner"] != self.runner.fingerprint():
                d.update(interventions=["environment/toolchain changed after approval"], test_review_mode="environment")
                return done("test.plan_review")
            if action["scope"]["bundle_id"] != bundle["id"] or action["scope"]["bundle_hash"] != bundle["hash"]:
                raise WorkflowError("Approved test bundle has changed")
            result = self.broker.execute(p, d["action_decision"], action["scope"], "testing", bundle["payload"]["files"], action["scope"]["tool"])
            emit("test_result", {**result, "bundle": bundle["id"], "action": d["test_action"]}, "runner")
            d["test_evidence"].append("@out:test_result")
            d["failure_count"] = 0 if result["passed"] else d.get("failure_count", 0) + 1
            return done("test.summarize")
        if state == "test.summarize":
            agent("test_summary", "test_summarizer", self.common(p, "test_plan", "test_action", "test_result"))
            return done("test.log")
        if state == "test.log":
            summary = self.payload(p, "test_summary")
            emit("action_log", {"action": d["test_action"], "decision": d["action_decision"], "raw_result": d["test_result"], "summary": d["test_summary"], "test_stage": 8})
            signals = []
            if d["failure_count"] >= 2:
                signals.append("repeated failure")
            if summary["confidence"] < .70:
                signals.append("low confidence in results")
            if signals:
                d.update(interventions=signals, test_review_mode="plan")
                return done("test.plan_review")
            if summary["next"] == "complete" and self.has_passing_evidence(p):
                return done("test.completion")
            return done("test.propose")
        if state == "test.completion":
            if not self.has_passing_evidence(p):
                raise WorkflowError("Completion requires passing tests and static checks for the current bundle")
            agent("test_completion", "completion", {**self.common(p, "test_plan", "test_bundle", "test_summary"), "execution_evidence": [self.ref(x) for x in d["test_evidence"]]})
            return done("test.verify")
        if state == "test.done":
            emit("test_signoff", {"approval": d["testing_decision"], "main": d["main"], "bundle": d["test_bundle"], "evidence": d["test_evidence"], "stage": 11})
            return done("deploy.assist")
        if state == "deploy.assist":
            agent("deployment_help", "deployment_assistant", self.common(p, "main", "adr", "test_signoff"))
            return done("deploy.manual")
        if state == "review.prepare":
            if isinstance(d.get("manual_deployment"), dict):
                emit("deployment_record", {**d["manual_deployment"], "approval": d["deployment_decision"], "performed_by": "human", "agent_executed": False})
            agent("review_pack", "review_facilitator", self.common(p, "main", "srs", "test_signoff"))
            return done("review.feedback")
        raise WorkflowError("State has no executable handler: " + state)

    @staticmethod
    def evidence_passes(evidence):
        checks = evidence.get("checks", {})
        return evidence.get("passed") is True and all(checks.get(c, {}).get("passed") is True for c in ("static_analysis", "python_tests")) and checks["python_tests"].get("tests_run", 0) > 0

    def has_passing_evidence(self, p):
        checks = {}
        for identifier in p["data"].get("test_evidence", []):
            report = self.store.artifact(identifier)["payload"]
            if report.get("bundle") != p["data"].get("test_bundle"):
                continue
            requested = ["static_analysis", "python_tests"] if report["tool"] == "python_checks" else [report["tool"]]
            for key in requested:
                checks[key] = report.get("checks", {}).get(key, {}).get("passed") is True and report.get("stopped") is None and report.get("exit_code") in (0, 1)
                if key == "python_tests":
                    checks[key] = checks[key] and report.get("checks", {}).get(key, {}).get("tests_run", 0) > 0
        return all(checks.get(key) is True for key in ("static_analysis", "python_tests"))

    def decide(self, project, gate_id, proposal_digest, action, feedback, payload, actor, token):
        self.store.authenticate(token)
        if action not in {"approve", "reject", "modify", "info"}:
            raise WorkflowError("Unknown human decision")
        if not feedback.strip() or not actor.strip():
            raise WorkflowError("Human identity and meaningful feedback are required")
        if not isinstance(payload, dict):
            raise WorkflowError("Decision payload must be a JSON object")
        p, gate = self.store.project(project), self.store.pending(project)
        if not gate or gate["id"] != gate_id or gate["digest"] != proposal_digest or p["status"] != "waiting":
            raise WorkflowError("Stale or mismatched checkpoint; inspect the current proposal")
        if action == "info":
            explanation = self.agents.run("explainer", {"question": feedback, "pending_proposal": gate["proposal"]})
            return self.store.information(p, gate, feedback, explanation, actor, token)
        d, state = copy.deepcopy(p["data"]), p["state"]
        d["feedback"].append({"state": state, "action": action, "text": feedback, "human_input": payload})
        next_state = getattr(GATES[state], action)
        iteration = p["iteration"]
        if state == "req.check" and action == "approve":
            d["requirements_decision"] = "@decision"
        if state in {"design.direction", "design.decision"}:
            if action == "approve":
                selection = payload.get("selection")
                if selection not in gate["proposal"]["selection_options"]:
                    raise WorkflowError("Select one displayed architecture option")
                if state == "design.direction":
                    d["design_direction"] = {"selection": selection, "feedback": feedback}
                    if d.get("direction_refined"):
                        next_state = "design.decision"
                else:
                    d.update(design_choice=selection, design_reason=feedback, architecture_decision="@decision")
            elif state == "design.decision":
                d["design_feedback_loop"] = True
            elif action == "modify":
                d["design_direction"] = {"feedback": feedback}
                d["design_feedback_loop"] = True
        if state == "dev.plan_review" and action == "approve":
            if payload.get("allow_evaluation") is not True:
                raise WorkflowError("Explicit allow_evaluation:true is required for the displayed sandbox recipes")
            selection = payload.get("selection")
            if selection not in {"A", "B", "custom"}:
                raise WorkflowError("Choose plan A, plan B, or custom")
            if selection == "custom":
                approach = payload.get("approach", "")
                if not isinstance(approach, str) or not approach.strip():
                    raise WorkflowError("A custom corrected approach needs text")
            else:
                plan = self.payload(p, "plan_" + selection.lower())
                approach = plan["approach"] + "\n" + "\n".join(plan["steps"])
            tests = {k: v for k, v in self.payload(p, "dev_base")["files"].items() if k.startswith("tests/")}
            tests.update(self.payload(p, "plan_a")["test_files"])
            tests.update(self.payload(p, "plan_b")["test_files"])
            d.update(approved_approach={"selection": selection, "approach": approach, "corrections": feedback}, dev_tests=tests, eval_scope=gate["proposal"]["execution_scope"], evaluation_decision="@decision")
        if state == "dev.final":
            if action == "approve":
                selection = payload.get("selection")
                if selection not in {"A", "B"}:
                    raise WorkflowError("Human must choose candidate A or B")
                if not self.evidence_passes(self.payload(p, "evidence_" + selection.lower())):
                    raise WorkflowError("Selected candidate has not passed tests/static analysis; request modifications")
                d.update(selected_candidate=selection, merge_decision="@decision")
            if action == "modify":
                if payload.get("allow_evaluation") is not True:
                    raise WorkflowError("Modification must renew bounded evaluation permission")
                d.update(dev_round=d["dev_round"] + 1, eval_scope=gate["proposal"]["execution_scope"], evaluation_decision="@decision")
                for key in ("evidence_a", "evidence_b", "review_a", "review_b", "candidate_diff"):
                    d.pop(key, None)
        if state == "test.plan_review" and action == "approve":
            next_state = "test.policy" if d.get("test_review_mode") == "action" else "test.propose"
            d["test_environment"] = self.runner.fingerprint()
            d["failure_count"] = 0
        if state == "test.policy" and action == "approve":
            policy = gate["proposal"]["policy"]
            if not policy["allowed"]:
                raise WorkflowError(policy["reason"])
            if gate["proposal"]["execution_scope"]["runner"] != self.runner.fingerprint():
                raise WorkflowError("Environment changed since proposal; reject and re-propose")
            d["action_decision"] = "@decision"
        if state == "test.verify" and action == "approve":
            if not self.has_passing_evidence(p):
                raise WorkflowError("Final verification needs passing measured tests and static analysis")
            d["testing_decision"] = "@decision"
        if state == "deploy.manual" and action == "approve":
            if payload.get("status") not in {"deployed", "deferred"} or not isinstance(payload.get("record"), str) or not payload["record"].strip():
                raise WorkflowError("Record the manual deployment or explicitly defer it")
            d.update(manual_deployment={"status": payload["status"], "record": payload["record"], "actor": actor}, deployment_decision="@decision")
        if state == "review.feedback" and action == "approve":
            if not isinstance(payload.get("demo_notes"), str) or not payload["demo_notes"].strip():
                raise WorkflowError("Record actual demonstration/stakeholder notes")
            new = payload.get("new_requirements", "")
            if isinstance(new, str) and new.strip():
                iteration += 1
                d = {"main": d["main"], "previous_srs": d["srs"], "seed": new, "feedback": [{"state": state, "action": "new_iteration", "text": feedback, "demo_notes": payload["demo_notes"]}], "dev_round": 1}
                next_state = "req.collect"
            elif payload.get("close") is not True:
                raise WorkflowError("Supply new_requirements or explicitly set close:true")
        return self.store.resolve(p, gate_id, proposal_digest, action, feedback, payload, actor, d, next_state, token, iteration)

    def recover(self, project, token):
        self.store.authenticate(token)
        p = self.store.project(project)
        if p["status"] == "running" and (p["lease_until"] or 0) > time.time():
            raise WorkflowError("The worker lease is still live; wait for expiry before recovery")
        if p["status"] in {"failed", "running"} and p["state"] in {"dev.evaluate", "test.execute"}:
            for execution in self.store.executions(project):
                if execution["status"] == "running":
                    self.runner.cancel(execution["id"])
        next_state = {"dev.evaluate": "dev.plan_review", "test.execute": "test.policy"}.get(p["state"], p["state"])
        self.store.recover(project, token, next_state)

    def source_rework(self, project, feedback, token):
        if not feedback.strip():
            raise WorkflowError("Describe the needed source correction")
        self.store.rework(project, feedback, token)

    def export(self, project):
        p = self.store.project(project)
        return {"project": p, "artifacts": [self.store.artifact(a["id"]) for a in self.store.artifacts(project)], "gates": self.store.gates(project), "decisions": self.store.decisions(project), "events": self.store.events(project), "executions": self.store.executions(project), "pending_gate": self.store.pending(project)}
