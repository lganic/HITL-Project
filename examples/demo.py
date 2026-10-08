"""Reproducible demonstration: scripted agents/human, real known-fixture checks."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from hitl_se.agents import Agents
from hitl_se.cli import console, export_source
from hitl_se.engine import Engine
from hitl_se.store import Store
from .fixtures import FixtureProvider, FixtureRunner, GOAL


def default_payload(state):
    return {
        "design.direction": {"selection": "library"},
        "design.decision": {"selection": "library"},
        "dev.plan_review": {"selection": "A", "allow_evaluation": True},
        "dev.final": {"selection": "A"},
        "deploy.manual": {"status": "deferred", "record": "DEMO: no deployment performed. Human-controlled deployment deferred."},
        "review.feedback": {"demo_notes": "DEMO: simulated stakeholder reviewed Unicode and invalid-input behavior.", "close": True},
    }.get(state, {})


def decision(engine, project, action="approve", payload=None, feedback="DEMO human inspected the proposal and evidence."):
    gate = engine.store.pending(project)
    return engine.decide(project, gate["id"], gate["digest"], action, feedback, default_payload(gate["state"]) if payload is None else payload, "DEMO_SIMULATED_HUMAN", engine.store.keyfile.read_text().strip())


def run_demo(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hitl-demo-state-") as temp:
        store = Store(temp)
        provider, runner = FixtureProvider(), FixtureRunner()
        engine = Engine(store, Agents(provider), runner)
        project = store.create("Unicode whitespace normalizer", GOAL, store.keyfile.read_text().strip())
        revised_req = refined = corrected = explained = rejected_action = False
        for _ in range(40):
            result = engine.run(project)
            if result["status"] == "complete":
                break
            state = result["gate"]["state"]
            if state == "req.check" and not revised_req:
                decision(engine, project, "reject", {}, "DEMO correction: explicitly include Unicode whitespace and reject non-string values.")
                revised_req = True
            elif state == "req.check" and not explained:
                decision(engine, project, "info", {}, "What prevents this requirement checker from being bypassed?")
                explained = True
            elif state == "design.decision" and not refined:
                decision(engine, project, "modify", {}, "Keep a pure library; explain why a network service is unnecessary for this task.")
                refined = True
            elif state == "dev.final" and not corrected:
                decision(engine, project, "modify", {"allow_evaluation": True}, "B fails the measured Unicode separator test. Correct B and rerun both candidates and independent reviews.")
                corrected = True
            elif state == "test.policy" and not rejected_action:
                decision(engine, project, "reject", {}, "Restate that both tests and static checks will execute, including the independent Unicode cases.")
                rejected_action = True
            else:
                decision(engine, project)
        else:
            raise RuntimeError("Demo did not complete")
        report = engine.export(project)
        assert report["project"]["state"] == "review.closed"
        assert len(runner.calls) == 5
        (destination / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        export_source(engine, project, destination / "accepted_source")
        export_source(engine, project, destination / "tested_source", tested=True)
        for key in ("srs", "adr", "review_a", "review_b", "candidate_diff", "test_signoff", "deployment_record"):
            (destination / f"{key}.json").write_text(json.dumps(engine.payload(store.project(project), key), indent=2) + "\n")
        rows = []
        for artifact in report["artifacts"]:
            if artifact["kind"] in {"evidence_a", "evidence_b", "test_result"}:
                item = artifact["payload"]
                rows.append(f"| {artifact['kind']} v{artifact['version']} | {item['checks'].get('python_tests', {}).get('tests_run', 0)} | {'PASS' if item['passed'] else 'FAIL'} | {artifact['id']} |")
        trace = [f"| {e['id']} | {e['state']} | {e['type']} | {e['payload'].get('next', '')} |" for e in report["events"] if e["type"] in {"step_completed", "human_decision", "information_requested"}]
        text = """# End-to-end demonstration

This is a deterministic demonstration of the real engine. **Agent responses and
human decisions are scripted and explicitly labelled.** Actual Python source is
tested by the exact-fixture runner. No paid/external LLM was invoked and nothing
was deployed. The live application uses a configurable HTTP LLM provider and
requires Docker to execute generated code.

Task: implement Unicode-aware `normalize_whitespace(text)` with strict type
validation. Candidate A uses split/join. Candidate B initially uses an ASCII-only
regex, fails a Unicode test, and is corrected to a Unicode-aware regex after the
human modification checkpoint. Both reviewers receive raw failures; neither
chooses or merges a candidate.

The run demonstrates requirements rejection, a pending-gate explanation,
architectural refinement and its feedback arrow, two development rounds,
independent reports, policy-gate rejection/re-proposal, all 11 testing stages,
manual deployment deferral, and stakeholder review closure.

## Measured executions

| Evidence | Unit tests | Result | Artifact |
|---|---:|---|---|
""" + "\n".join(rows) + """

`accepted_source/` contains the merged implementation and locked acceptance
tests; `tested_source/` adds the independent testing suite. `audit.json` includes
full raw outputs, all artifact versions, proposals, decisions and execution
authorization records. No human key or API credential is included.

## Recorded workflow trace

| Event | State | Event type | Next state |
|---:|---|---|---|
""" + "\n".join(trace) + "\n"
        (destination / "DEMO_REPORT.md").write_text(text)
        print(f"Demo completed: {destination}")
        print("5 real fixture executions; scripted agents/humans; no deployment.")
        return report


def interactive_demo(workspace):
    print("KNOWN-FIXTURE DEMO: agent responses are scripted; you make the human decisions.")
    print("Task is fixed to the Unicode normalizer. No live LLM or deployment is used.")
    store = Store(workspace)
    engine = Engine(store, Agents(FixtureProvider()), FixtureRunner())
    projects = store.projects()
    project = projects[-1]["id"] if projects else store.create("Interactive normalizer demo", GOAL, store.keyfile.read_text().strip())
    console(engine, project, "interactive_demo_human")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="demo_output")
    parser.add_argument("--interactive", action="store_true", help="Use scripted agents with real interactive human decisions")
    parser.add_argument("--workspace", default=".hitl-demo", help="Persistent state for the interactive fixture demo")
    args = parser.parse_args()
    if args.interactive:
        interactive_demo(args.workspace)
    else:
        run_demo(args.out)
