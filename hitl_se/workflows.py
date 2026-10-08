"""Executable registry. Transitions with guards live in Engine, not in LLM output."""
from dataclasses import dataclass


@dataclass(frozen=True)
class GateSpec:
    title: str
    approve: str
    reject: str
    modify: str
    requirement: str


GATES = {
    "req.clarify": GateSpec("Stakeholder answers", "req.collect", "req.collect", "req.collect", "REQ-01"),
    "req.check": GateSpec("Human requirements checker", "req.document", "req.collect", "req.collect", "REQ-02"),
    "design.direction": GateSpec("Human architectural direction", "design.refine", "design.explore", "design.refine", "DES-02"),
    "design.decision": GateSpec("Human architectural decision", "design.record", "design.refine", "design.refine", "DES-02"),
    "dev.plan_review": GateSpec("Development checkpoint 1: approach and evaluation scope", "dev.implement_a", "dev.plan_a", "dev.plan_a", "DEV-01"),
    "dev.final": GateSpec("Development checkpoint 2: comparative decision", "dev.merge", "dev.plan_a", "dev.implement_a", "DEV-05"),
    "test.plan_review": GateSpec("Testing 3: human plan review", "test.propose", "test.prepare", "test.prepare", "TST-01"),
    "test.policy": GateSpec("Testing 5: human and policy permission", "test.execute", "test.propose", "test.propose", "TST-02"),
    "test.verify": GateSpec("Testing 10: human verification and sign-off", "test.done", "test.prepare", "test.prepare", "TST-04"),
    "deploy.manual": GateSpec("Human-controlled deployment record", "review.prepare", "deploy.assist", "deploy.assist", "DEP-01"),
    "review.feedback": GateSpec("Stakeholder demonstration and feedback", "review.closed", "review.prepare", "review.prepare", "REV-01"),
}

WORKFLOWS = {
    "requirements": ["req.collect", "req.clarify", "req.model", "req.check", "req.document"],
    "design": ["design.explore", "design.direction", "design.refine", "design.decision", "design.record"],
    "development": ["dev.plan_a", "dev.plan_b", "dev.plan_review", "dev.implement_a", "dev.implement_b", "dev.evaluate", "dev.review_a", "dev.review_b", "dev.final", "dev.merge"],
    "testing": ["test.context", "test.prepare", "test.plan_review", "test.propose", "test.policy", "test.execute", "test.summarize", "test.log", "test.completion", "test.verify", "test.done"],
    "deployment": ["deploy.assist", "deploy.manual"],
    "review": ["review.prepare", "review.feedback", "review.closed"],
}
STATES = {s for workflow in WORKFLOWS.values() for s in workflow}
TEST_STAGES = {s: i + 1 for i, s in enumerate(WORKFLOWS["testing"])}
