"""Human-authored fixed demo data. This is not live model output."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from hitl_se.agents import references
from hitl_se.runner import HARNESS, capture, parse_result
from hitl_se.util import WorkflowError, digest

GOAL = "Create solution.py with normalize_whitespace(text): collapse every Unicode whitespace run to one ASCII space, trim ends, return empty for whitespace-only input, and raise TypeError for non-string input. No external dependencies."

SOLUTION_A = '''def normalize_whitespace(text):
    """Normalize Unicode whitespace; require a string."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return " ".join(text.split())
'''
SOLUTION_B_BAD = '''import re

def normalize_whitespace(text):
    """Collapse whitespace with an explicit regular expression."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return re.sub(r"[ \\t\\r\\n]+", " ", text).strip()
'''
SOLUTION_B = SOLUTION_B_BAD.replace(r"[ \t\r\n]+", r"\s+")
TEST_A = '''import unittest
from solution import normalize_whitespace

class ContractTests(unittest.TestCase):
    def test_words(self):
        self.assertEqual(normalize_whitespace("  hello   world  "), "hello world")
    def test_empty(self):
        self.assertEqual(normalize_whitespace(""), "")
        self.assertEqual(normalize_whitespace(" \\n\\t"), "")
    def test_bad_input(self):
        for value in [None, 42, [], b"hello"]:
            with self.assertRaises(TypeError):
                normalize_whitespace(value)
'''
TEST_B = '''import unittest
from solution import normalize_whitespace

class BoundaryTests(unittest.TestCase):
    def test_unicode_separator(self):
        self.assertEqual(normalize_whitespace("alpha\\u00a0beta\\u2003gamma"), "alpha beta gamma")
    def test_line_breaks(self):
        self.assertEqual(normalize_whitespace("a\\n\\tb\\rc"), "a b c")
    def test_single_word(self):
        self.assertEqual(normalize_whitespace("xyz"), "xyz")
'''
TEST_EXTRA = '''import unittest
from solution import normalize_whitespace

class IndependentTests(unittest.TestCase):
    def test_idempotent(self):
        for text in [" \\thello\\u2003world ", "", "a  b"]:
            result = normalize_whitespace(text)
            self.assertEqual(normalize_whitespace(result), result)
    def test_unicode_only(self):
        self.assertEqual(normalize_whitespace("\\u00a0\\u2003"), "")
'''
REQUIREMENTS = [
    {"id": "REQ-1", "statement": "normalize_whitespace collapses Unicode whitespace and trims ends", "acceptance": ["ASCII and Unicode separators become one ASCII space", "Empty and whitespace-only inputs return empty"], "priority": "must"},
    {"id": "REQ-2", "statement": "Non-string values raise TypeError", "acceptance": ["None, integers, lists, and bytes raise TypeError"], "priority": "must"},
]


class FixtureProvider:
    """Scripted roles for reproducible tests/demo. Only the explicitly selected demo interfaces use this."""
    def __init__(self):
        self.calls = []
        self.fail_once = None
        self.override = {}

    def complete(self, role, messages, schema):
        context = json.loads(messages[1]["content"])
        self.calls.append({"role": role, "context": context, "system": messages[0]["content"]})
        if self.fail_once == role:
            self.fail_once = None
            raise WorkflowError("Scripted transient agent failure")
        refs = sorted(references(context))
        common = {"summary": "Scripted demo: " + role, "rationale": "Demonstrate the source-defined workflow using a small deterministic task.", "risks": ["This is scripted demo data, not live LLM reasoning."], "alternatives": ["Inspect source and raw tests before deciding."]}
        out = {}
        if role == "collector":
            out = {"requirements": REQUIREMENTS, "questions": [], "assumptions": ["Python standard library only"]}
        elif role == "modeler":
            out = {"requirements": REQUIREMENTS, "entities": [{"name": "Text", "attributes": ["Unicode string"]}], "relationships": [], "constraints": ["No external dependencies"], "assumptions": ["Whitespace is defined by Python Unicode string handling"]}
        elif role == "documenter":
            out = {"overview": "A deterministic Unicode whitespace normalization library.", "glossary": {"whitespace": "Unicode characters treated as whitespace by Python"}}
        elif role == "design_search":
            out = {"queries": ["pure function library deterministic transformation", "modular monolith overhead"], "criteria": ["Correct Unicode behavior", "Minimal operational cost"]}
        elif role in {"architect", "refiner"}:
            evidence = [r for r in refs if r.startswith("pattern:")] or refs[:1]
            out = {"options": [{"id": "library", "description": "A pure function in solution.py", "tradeoffs": ["Small interface; no network API"], "evidence": evidence[:1]}, {"id": "service", "description": "Wrap the function behind a service boundary", "tradeoffs": ["Remote access adds operational overhead"], "evidence": evidence[-1:]}], "recommendation": "The library fits the current scope; human makes the choice."}
        elif role in {"planner_a", "planner_b"}:
            side = role[-1].upper()
            out = {"approach": "Pure function contract with independent internals", "steps": ["Validate string type", "Normalize Unicode whitespace", "Verify both locked test suites"], "test_files": {f"tests/test_{side}_contract.py": TEST_A if side == "A" else TEST_B}, "acceptance_mapping": [{"requirement": "REQ-1", "test": "test_words" if side == "A" else "test_unicode_separator"}, {"requirement": "REQ-2", "test": "test_bad_input"}], "assumptions": ["Public function name is normalize_whitespace"]}
        elif role in {"implementer_a", "implementer_b"}:
            corrected = any(x.get("state") == "dev.final" and x.get("action") == "modify" for x in context["human_feedback"])
            source = SOLUTION_A if role.endswith("a") else (SOLUTION_B if corrected else SOLUTION_B_BAD)
            out = {"files": {"solution.py": source}}
        elif role.startswith("reviewer_"):
            evidence = [context["evidence_a"]["artifact_id"], context["evidence_b"]["artifact_id"]]
            b_failed = not context["evidence_b"]["content"]["passed"]
            fact = lambda claim: {"claim": claim, "evidence": evidence}
            source_refs = [context["candidate_a"]["artifact_id"], context["candidate_b"]["artifact_id"], context["candidate_diff"]["artifact_id"]]
            out = {"differences": [{"claim": "A uses split/join; B uses a regular expression, as visible in the candidates.", "evidence": source_refs}], "failures": [fact("B fails the Unicode separator assertion; A passes the six planned tests.")] if b_failed else [], "risk_analysis": [fact("The small suite does not establish performance bounds for very large inputs.")], "tradeoffs": [{"claim": "A is shorter; B makes its matching policy explicit but adds regex machinery.", "evidence": source_refs}], "recommendation": "Request correction of B's Unicode handling." if b_failed else "Both pass; inspect the implementation tradeoff and make the human selection."}
        elif role == "test_planner":
            out = {"objective": "Verify the merged source and independent edge cases", "test_files": {"tests/test_extra_invariants.py": TEST_EXTRA}, "success_criteria": ["All eight tests pass", "No syntax errors"], "constraints": ["No network"], "assumptions": ["Python Unicode semantics"], "confidence": .9}
        elif role == "test_proposer":
            out = {"tool": "python_checks", "expected_result": "Static checks and eight tests pass", "side_effects": ["Imports source inside the sandbox"], "confidence": .9, "strategy_changed": False, "environment_changed": False}
        elif role == "test_summarizer":
            success = context["test_result"]["content"]["passed"]
            out = {"observations": ["Measured checks passed" if success else "Measured checks failed; raw output retained"], "next": "complete" if success else "continue", "confidence": .9}
        elif role == "completion":
            out = {"evidence": [x["artifact_id"] for x in context["execution_evidence"]], "remaining_work": []}
        elif role == "deployment_assistant":
            out = {"instructions": ["Human: export the reviewed source and inspect the target environment.", "Human: run the reviewed tests, then install the library using your own release process."], "rollback": ["Keep the previous reviewed release and restore it manually if needed."]}
        elif role == "review_facilitator":
            out = {"demo_steps": ["Show ASCII and Unicode normalization", "Show invalid-input behavior and test evidence"], "stakeholder_questions": ["Does this cover your expected input sources?", "Are performance or additional transformations needed?"]}
        elif role == "explainer":
            out = {"answer": "This gate remains pending. Inspect the named artifacts and measured outputs; the model cannot approve its own work.", "evidence": refs[:2]}
        else:
            raise AssertionError(role)
        result = {**common, **out}
        override = self.override.get(role)
        if override:
            result.update(override(context) if callable(override) else override)
        return result, {"provider": "scripted-demo-fixture", "model": "none", "usage": {}}


class FixtureRunner:
    """Only exact known demo strings can reach the host interpreter. NOT a sandbox."""
    def __init__(self):
        self.calls = []
        self.environment_revision = 1
        self.force_failure = False

    def fingerprint(self):
        return digest({"fixture_only": True, "revision": self.environment_revision, "harness": HARNESS.read_text()})

    def cancel(self, execution_id):
        # Fixed fixtures finish within ten seconds; this test adapter never
        # creates persistent containers or launches unreviewed source.
        return None

    def run(self, files, tool, execution_id):
        allowed = {"tests/test_A_contract.py": TEST_A, "tests/test_B_contract.py": TEST_B, "tests/test_extra_invariants.py": TEST_EXTRA}
        if files.get("solution.py") not in {SOLUTION_A, SOLUTION_B, SOLUTION_B_BAD}:
            raise WorkflowError("Fixture runner refuses unknown source; use a real sandbox")
        if set(files) - ({"solution.py"} | allowed.keys()) or not {"tests/test_A_contract.py", "tests/test_B_contract.py"}.issubset(files):
            raise WorkflowError("Fixture runner refuses unknown files or missing tests")
        if any(files[k] != allowed[k] for k in files if k != "solution.py"):
            raise WorkflowError("Fixture runner refuses modified test content")
        self.calls.append({"tool": tool, "execution_id": execution_id, "tree_hash": digest(files)})
        with tempfile.TemporaryDirectory(prefix="hitl-known-fixture-") as tmp:
            root = Path(tmp)
            for name, source in files.items():
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(source, encoding="utf-8")
            raw = capture([sys.executable, "-I", str(HARNESS), str(root), tool], timeout=10, limit=65536, env={})
        result = parse_result(raw)
        if self.force_failure:
            result.update(passed=False, exit_code=1, checks={"python_tests": {"passed": False, "tests_run": 8}, "static_analysis": {"passed": True}})
        return {**result, "execution_mode": "known_fixture_only; not live model code"}
