import copy
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from hitl_se.agents import Agents
from hitl_se.cli import console
from hitl_se.engine import Engine
from hitl_se.store import Store
from hitl_se.util import WorkflowError, digest, validate_files
from hitl_se.workflows import WORKFLOWS, GATES
from examples.fixtures import FixtureProvider, FixtureRunner, GOAL, SOLUTION_A, SOLUTION_B
from examples.demo import default_payload


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.provider, self.runner = FixtureProvider(), FixtureRunner()
        self.engine = Engine(self.store, Agents(self.provider), self.runner)
        self.token = self.store.keyfile.read_text().strip()
        self.project = self.store.create("Test normalizer", GOAL, self.token)

    def decide(self, action="approve", payload=None, feedback="Human reviewed the exact proposal and evidence."):
        gate = self.store.pending(self.project)
        return self.engine.decide(self.project, gate["id"], gate["digest"], action, feedback, default_payload(gate["state"]) if payload is None else payload, "test_human", self.token)

    def reach(self, state):
        for _ in range(30):
            result = self.engine.run(self.project)
            if self.store.project(self.project)["state"] == state:
                return result
            if result["status"] != "waiting":
                self.fail(f"Could not reach {state}")
            self.decide()
        self.fail("Gate budget exceeded")

    def test_complete_sequence_and_all_eleven_testing_stages(self):
        self.reach("review.feedback")
        self.decide()
        self.assertEqual(self.engine.run(self.project)["status"], "complete")
        events = self.store.events(self.project)
        transitions = [e["state"] for e in events if e["type"] in {"step_completed", "human_decision"}]
        testing = [s for s in transitions if s.startswith("test.")]
        self.assertEqual(testing, WORKFLOWS["testing"])
        self.assertLess(transitions.index("dev.plan_review"), transitions.index("dev.implement_a"))
        self.assertLess(transitions.index("dev.evaluate"), transitions.index("dev.review_a"))
        self.assertLess(transitions.index("dev.final"), transitions.index("dev.merge"))
        self.assertEqual(len(self.runner.calls), 3)
        p = self.store.project(self.project)
        self.assertEqual(self.engine.payload(p, "main")["files"]["solution.py"], SOLUTION_A)
        self.assertEqual(self.engine.payload(p, "deployment_record")["status"], "deferred")
        self.assertFalse(self.engine.payload(p, "deployment_record")["agent_executed"])

    def test_pending_gate_never_advances_or_executes(self):
        self.reach("dev.plan_review")
        calls, runs = len(self.provider.calls), len(self.runner.calls)
        for _ in range(3):
            self.assertEqual(self.engine.run(self.project)["status"], "waiting")
        self.assertEqual(len(self.provider.calls), calls)
        self.assertEqual(len(self.runner.calls), runs)
        self.assertFalse(any(c["role"].startswith("implementer") for c in self.provider.calls))

    def test_invalid_human_credential_and_stale_digest(self):
        self.reach("req.check")
        gate = self.store.pending(self.project)
        for token, dgst in [("agent", gate["digest"]), (self.token, "stale")]:
            with self.assertRaises(WorkflowError):
                self.engine.decide(self.project, gate["id"], dgst, "approve", "Fake authorization", {}, "agent", token)
        self.assertEqual(self.store.project(self.project)["state"], "req.check")
        self.decide()
        with self.assertRaises(WorkflowError):
            self.engine.decide(self.project, gate["id"], gate["digest"], "approve", "Replay", {}, "human", self.token)

    def test_agent_cannot_self_approve_through_output(self):
        self.provider.override["collector"] = {"approved": True, "next_state": "dev.merge"}
        with self.assertRaises(WorkflowError):
            self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "req.collect")
        self.assertEqual(self.store.project(self.project)["status"], "failed")
        self.assertEqual(len(self.runner.calls), 0)

    def test_requirements_reject_and_exact_canonical_srs(self):
        self.reach("req.check")
        old_model = self.store.project(self.project)["data"]["model"]
        self.decide("reject", {}, "Need Unicode acceptance criteria")
        self.assertEqual(self.store.project(self.project)["state"], "req.collect")
        self.reach("req.check")
        self.assertNotEqual(self.store.project(self.project)["data"]["model"], old_model)
        self.decide()
        self.engine.step(self.project)
        p = self.store.project(self.project)
        self.assertEqual(self.engine.payload(p, "srs")["requirements"], self.engine.payload(p, "model")["requirements"])

    def test_collector_questions_return_to_human_stakeholder(self):
        self.provider.override["collector"] = lambda c: {"questions": [] if c["human_feedback"] else ["Should Unicode whitespace count?"]}
        self.reach("req.clarify")
        self.assertFalse(any(c["role"] == "modeler" for c in self.provider.calls))
        self.decide(payload={}, feedback="Yes, Unicode whitespace must count.")
        self.reach("req.check")
        self.assertEqual(len([c for c in self.provider.calls if c["role"] == "collector"]), 2)

    def test_information_request_keeps_pending_gate(self):
        self.reach("req.check")
        before = self.store.pending(self.project)
        art = self.decide("info", {}, "Which assumptions remain?")
        self.assertEqual(self.store.pending(self.project)["id"], before["id"])
        self.assertEqual(self.store.artifact(art)["kind"], "explanation")
        self.assertEqual(self.engine.run(self.project)["status"], "waiting")

    def test_explainer_failure_preserves_pending_gate(self):
        self.reach("req.check")
        self.provider.fail_once = "explainer"
        with self.assertRaises(WorkflowError):
            self.decide("info", {}, "Explain the ambiguity")
        self.assertEqual(self.store.project(self.project)["status"], "waiting")
        self.decide("info", {}, "Retry explanation")

    def test_design_feedback_arrow_and_human_selected_adr(self):
        self.reach("design.decision")
        self.decide("modify", {}, "Reassess service boundary.")
        self.assertEqual(self.store.project(self.project)["state"], "design.refine")
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "design.direction")
        self.decide(payload={"selection": "service"})
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "design.decision")
        self.decide(payload={"selection": "service"}, feedback="Human chooses the service despite the agent recommendation.")
        self.engine.step(self.project)
        self.assertEqual(self.engine.payload(self.store.project(self.project), "adr")["decision"]["id"], "service")

    def test_design_search_has_real_catalog_observations(self):
        self.reach("design.direction")
        ctx = next(c["context"] for c in self.provider.calls if c["role"] == "architect")
        self.assertTrue(ctx["observations"][0]["results"])
        self.assertGreaterEqual(len(self.engine.payload(self.store.project(self.project), "design_options")["options"]), 2)

    def test_independent_contexts_implementations_and_reviewers(self):
        self.reach("dev.final")
        calls = {c["role"]: c for c in self.provider.calls}
        self.assertNotIn("plan_a", calls["planner_b"]["context"])
        self.assertNotIn("candidate_a", calls["implementer_b"]["context"])
        self.assertNotIn("plan_a", calls["implementer_b"]["context"])
        self.assertNotIn("review_a", calls["reviewer_b"]["context"])
        self.assertNotEqual(calls["implementer_a"]["system"], calls["implementer_b"]["system"])
        for role in ("reviewer_a", "reviewer_b"):
            self.assertIn("candidate_a", calls[role]["context"])
            self.assertIn("candidate_b", calls[role]["context"])
        p = self.store.project(self.project)
        self.assertNotEqual(self.engine.payload(p, "candidate_a")["files"], self.engine.payload(p, "candidate_b")["files"])
        self.assertTrue(self.engine.payload(p, "review_a")["failures"])

    def test_no_numerical_score_or_fabricated_evidence(self):
        self.reach("dev.plan_review")
        self.decide()
        self.provider.override["reviewer_a"] = {"score": 3}
        with self.assertRaises(WorkflowError):
            self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "dev.review_a")
        self.provider.override["reviewer_a"] = {"differences": [{"claim": "Made up", "evidence": ["art_unknown"]}]}
        self.engine.recover(self.project, self.token)
        with self.assertRaises(WorkflowError):
            self.engine.run(self.project)

    def test_explicit_evaluation_permission_required(self):
        self.reach("dev.plan_review")
        with self.assertRaises(WorkflowError):
            self.decide(payload={"selection": "A"})
        self.assertEqual(len(self.runner.calls), 0)

    def test_failed_candidate_cannot_merge_and_modification_is_reevaluated(self):
        self.reach("dev.final")
        old_main = self.store.project(self.project)["data"]["main"]
        with self.assertRaises(WorkflowError):
            self.decide(payload={"selection": "B"})
        self.assertEqual(self.store.project(self.project)["data"]["main"], old_main)
        self.decide("modify", {"allow_evaluation": True}, "Fix B Unicode behavior")
        self.assertEqual(self.store.project(self.project)["state"], "dev.implement_a")
        self.reach("dev.final")
        self.assertEqual(len(self.runner.calls), 4)
        self.assertEqual(len([c for c in self.provider.calls if c["role"] == "reviewer_a"]), 2)
        self.assertEqual(self.engine.payload(self.store.project(self.project), "candidate_b")["files"]["solution.py"], SOLUTION_B)
        self.decide(payload={"selection": "B"})
        self.engine.step(self.project)
        self.assertEqual(self.engine.payload(self.store.project(self.project), "main")["parent"], old_main)

    def test_testing_policy_cannot_execute_deployment_even_with_human_approval(self):
        self.provider.override["test_proposer"] = {"tool": "deploy"}
        self.reach("test.policy")
        runs = len(self.runner.calls)
        with self.assertRaises(WorkflowError):
            self.decide()
        self.assertEqual(len(self.runner.calls), runs)
        self.assertEqual(self.store.project(self.project)["status"], "waiting")
        self.decide("reject", {}, "Use a permitted testing recipe")
        self.assertEqual(self.store.project(self.project)["state"], "test.propose")

    def test_test_policy_stops_until_approval_and_is_exactly_once(self):
        self.reach("test.policy")
        self.assertEqual(len(self.runner.calls), 2)
        self.engine.run(self.project)
        self.assertEqual(len(self.runner.calls), 2)
        self.decide()
        p = self.store.claim(self.project, 600)
        action = self.engine.payload(p, "test_action")
        bundle = self.engine.payload(p, "test_bundle")
        args = (p, p["data"]["action_decision"], action["scope"], "testing", bundle["files"], "python_checks")
        self.engine.broker.execute(*args)
        with self.assertRaises(WorkflowError):
            self.engine.broker.execute(*args)
        self.assertEqual(len(self.runner.calls), 3)

    def test_broker_rejects_substituted_files_recipes_and_missing_decision(self):
        self.reach("test.policy")
        self.decide()
        p = self.store.claim(self.project, 600)
        action = self.engine.payload(p, "test_action")
        files = self.engine.payload(p, "test_bundle")["files"]
        changed = {**files, "solution.py": "raise RuntimeError('substitution')"}
        for decision, source, tool in [(p["data"]["action_decision"], changed, "python_checks"), (p["data"]["action_decision"], files, "static_analysis"), ("dec_fake", files, "python_checks")]:
            with self.subTest(tool=tool), self.assertRaises(WorkflowError):
                self.engine.broker.execute(p, decision, action["scope"], "testing", source, tool)
        self.assertEqual(len(self.runner.calls), 2)

    def test_interrupted_development_evaluation_requires_checkpoint_one(self):
        self.reach("dev.plan_review")
        self.decide()
        self.engine.step(self.project)
        self.engine.step(self.project)
        self.store.claim(self.project, 600)
        with self.store.transaction() as conn:
            conn.execute("UPDATE projects SET lease_until=0 WHERE id=?", (self.project,))
        self.engine.recover(self.project, self.token)
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "dev.plan_review")
        self.assertEqual(len(self.runner.calls), 0)

    def test_environment_change_after_permission_cannot_execute(self):
        self.reach("test.policy")
        self.decide()
        self.runner.environment_revision += 1
        self.engine.step(self.project)
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(self.store.project(self.project)["state"], "test.plan_review")

    def test_development_environment_change_returns_to_checkpoint_one(self):
        self.reach("dev.plan_review")
        self.decide()
        self.engine.step(self.project)
        self.engine.step(self.project)
        self.runner.environment_revision += 1
        self.engine.step(self.project)
        self.assertEqual(len(self.runner.calls), 0)
        self.assertEqual(self.store.project(self.project)["state"], "dev.plan_review")

    def test_low_confidence_and_strategy_change_force_plan_review(self):
        self.provider.override["test_proposer"] = {"confidence": .3, "strategy_changed": True, "environment_changed": True}
        self.reach("test.plan_review")
        self.decide()
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "test.plan_review")
        self.assertEqual(len(self.store.pending(self.project)["proposal"]["interventions"]), 3)
        self.decide()
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "test.policy")
        self.assertEqual(len(self.runner.calls), 2)

    def test_repeated_failure_returns_to_plan_review_and_retains_raw_logs(self):
        self.reach("test.policy")
        self.runner.force_failure = True
        self.decide()
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "test.policy")
        self.decide()
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "test.plan_review")
        p = self.store.project(self.project)
        self.assertEqual(len(p["data"]["test_evidence"]), 2)
        self.assertTrue(self.engine.payload(p, "test_result")["stderr"])
        self.assertIn("repeated failure", p["data"]["interventions"])

    def test_static_only_cannot_complete_then_evidence_can_accumulate(self):
        self.provider.override["test_proposer"] = {"tool": "static_analysis"}
        self.reach("test.policy")
        self.decide()
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "test.policy")
        self.decide("reject", {}, "Need real unit-test evidence too")
        self.provider.override["test_proposer"] = {"tool": "python_tests"}
        self.engine.run(self.project)
        self.decide()
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "test.verify")
        self.assertTrue(self.engine.has_passing_evidence(self.store.project(self.project)))

    def test_final_verification_is_human_and_rejection_replans(self):
        self.reach("test.verify")
        calls = len(self.provider.calls)
        self.engine.run(self.project)
        self.assertEqual(len(self.provider.calls), calls)
        self.decide("reject", {}, "Need more acceptance evidence")
        self.assertEqual(self.store.project(self.project)["state"], "test.prepare")

    def test_stakeholder_feedback_reenters_requirements_with_baseline(self):
        self.reach("review.feedback")
        before = self.store.project(self.project)
        self.decide(payload={"demo_notes": "Stakeholder reviewed the demo", "new_requirements": "Add a maximum-length validation option"})
        after = self.store.project(self.project)
        self.assertEqual(after["state"], "req.collect")
        self.assertEqual(after["iteration"], 2)
        self.assertEqual(after["data"]["main"], before["data"]["main"])
        self.assertNotIn("merge_decision", after["data"])
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "req.check")

    def test_deployment_record_requires_manual_attestation(self):
        self.reach("deploy.manual")
        runs = len(self.runner.calls)
        with self.assertRaises(WorkflowError):
            self.decide(payload={})
        self.decide(payload={"status": "deployed", "record": "Human installed it in an isolated local demo directory."})
        self.engine.run(self.project)
        self.assertEqual(len(self.runner.calls), runs)
        self.assertEqual(self.engine.payload(self.store.project(self.project), "deployment_record")["performed_by"], "human")

    def test_agent_failure_recovery_and_restart(self):
        self.reach("dev.plan_review")
        self.decide()
        self.provider.fail_once = "implementer_a"
        with self.assertRaises(WorkflowError):
            self.engine.run(self.project)
        self.store = Store(self.tmp.name)
        self.engine = Engine(self.store, Agents(self.provider), self.runner)
        self.assertEqual(self.store.project(self.project)["status"], "failed")
        self.engine.recover(self.project, self.token)
        self.reach("dev.final")
        self.assertEqual(len([d for d in self.store.decisions(self.project) if d["payload"].get("allow_evaluation")]), 1)

    def test_pending_approval_survives_restart(self):
        self.reach("req.check")
        gate = self.store.pending(self.project)
        restarted = Engine(Store(self.tmp.name), Agents(self.provider), self.runner)
        self.assertEqual(restarted.run(self.project)["gate"]["digest"], gate["digest"])
        self.assertEqual(restarted.store.keyfile.read_text().strip(), self.token)

    def test_unknown_execution_recovery_requires_new_policy_gate(self):
        self.reach("test.policy")
        self.decide()
        p = self.store.claim(self.project, 600)
        action = self.engine.payload(p, "test_action")
        self.store.begin_execution(p, p["data"]["action_decision"], action["scope"], "testing")
        with self.assertRaises(WorkflowError):
            self.engine.recover(self.project, self.token)
        with self.store.transaction() as conn:
            conn.execute("UPDATE projects SET lease_until=0 WHERE id=?", (self.project,))
        self.engine.recover(self.project, self.token)
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "test.policy")
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(self.store.executions(self.project)[-1]["status"], "uncertain")
        self.decide()
        self.engine.run(self.project)
        self.assertEqual(self.store.project(self.project)["state"], "test.verify")

    def test_project_lease_prevents_two_workers(self):
        self.store.claim(self.project, 600)
        with self.assertRaises(WorkflowError):
            Store(self.tmp.name).claim(self.project, 600)

    def test_artifacts_and_decisions_are_immutable(self):
        self.reach("req.check")
        artifact = self.store.project(self.project)["data"]["model"]
        with self.assertRaises(sqlite3.IntegrityError), self.store.transaction() as conn:
            conn.execute("UPDATE artifacts SET payload='{}' WHERE id=?", (artifact,))

    def test_audit_export_preserves_resolved_proposals_without_credentials(self):
        self.reach("design.direction")
        report = self.engine.export(self.project)
        gates = {gate["id"]: gate for gate in report["gates"]}
        for decision in report["decisions"]:
            gate = gates[decision["gate_id"]]
            self.assertEqual(decision["proposal_digest"], digest(gate["proposal"]))
            self.assertTrue(gate["proposal"]["artifacts"])
        self.assertNotIn(self.token, json.dumps(report))
        with self.assertRaises(sqlite3.IntegrityError), self.store.transaction() as conn:
            conn.execute("UPDATE gates SET proposal='{}' WHERE project=?", (self.project,))

    def test_source_rework_invalidates_testing_approval_and_replans(self):
        self.reach("test.policy")
        gate = self.store.pending(self.project)
        self.engine.source_rework(self.project, "Need to fix production code", self.token)
        self.assertEqual(self.store.project(self.project)["state"], "dev.plan_a")
        self.assertIsNone(self.store.pending(self.project))
        with self.assertRaises(WorkflowError):
            self.engine.decide(self.project, gate["id"], gate["digest"], "approve", "Old gate", {}, "human", self.token)

    def test_unsafe_paths_and_acceptance_test_mutation_are_rejected(self):
        for path in ("../evil.py", "/tmp/evil.py", ".git/hooks/pre-commit", "a/../../x.py", "x\\y.py"):
            with self.subTest(path=path), self.assertRaises(WorkflowError):
                validate_files({path: "bad"})
        with self.assertRaises(WorkflowError):
            validate_files({"tests/test_A_contract.py": "weakened"}, implementation=True)

    def test_text_web_assets_are_supported_without_relaxing_path_guards(self):
        files = {"web/index.html": "<!doctype html>", "web/style.css": "body {}",
                 "web/app.js": "console.log('ready')", "web/module.mjs": "export {}",
                 "web/icon.svg": "<svg></svg>"}
        self.assertEqual(validate_files(files, implementation=True), files)
        for path in ("../web/index.html", ".git/index.html", "hitl_se/web/index.html", "tests/test_ui.html"):
            with self.subTest(path=path), self.assertRaises(WorkflowError):
                validate_files({path: "text"}, implementation=True)
        with self.assertRaises(WorkflowError):
            validate_files({"tests/test_web.html": "text"}, tests_only=True)

    def test_fixture_runner_refuses_model_generated_or_changed_code(self):
        with self.assertRaises(WorkflowError):
            self.runner.run({"solution.py": "import os; os.system('bad')"}, "python_checks", "fake")

    def test_gate_reject_routes(self):
        # Distinct branch checks through real reached gates, not registry equality.
        expected = {"design.direction": "design.explore", "dev.plan_review": "dev.plan_a", "dev.final": "dev.plan_a", "test.plan_review": "test.prepare", "deploy.manual": "deploy.assist", "review.feedback": "review.prepare"}
        for state, target in expected.items():
            with self.subTest(state=state):
                self.project = self.store.create(state, GOAL, self.token)
                self.reach(state)
                self.decide("reject", {}, "Human requests revision")
                self.assertEqual(self.store.project(self.project)["state"], target)

    def test_interactive_console_can_reject_inspect_and_resume(self):
        inputs = ["run", "show", "decide", "reject", "Need explicit Unicode requirements", "run", "quit"]
        with patch("builtins.input", side_effect=inputs), contextlib.redirect_stdout(io.StringIO()) as output:
            console(self.engine, self.project, "interactive_human")
        self.assertEqual(self.store.project(self.project)["state"], "req.check")
        self.assertEqual(len([c for c in self.provider.calls if c["role"] == "collector"]), 2)
        self.assertIn("HUMAN CHECKPOINT", output.getvalue())


if __name__ == "__main__":
    unittest.main()
