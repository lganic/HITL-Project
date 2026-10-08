from .util import WorkflowError, digest

RECIPES = {
    "static_analysis": {"command": "python -I <trusted-check-harness> static_analysis", "effects": ["Parse project Python files and report syntax errors/risky constructs; no project imports"]},
    "python_tests": {"command": "python -I <trusted-check-harness> python_tests", "effects": ["Import project code and execute unittest tests in an isolated container"]},
    "python_checks": {"command": "python -I <trusted-check-harness> python_checks", "effects": ["Run static analysis, then Python unittest discovery in an isolated container"]},
}


def inspect_policy(tool):
    if tool not in RECIPES:
        return {"allowed": False, "reason": "Denied: unknown actions, arbitrary commands, and deployment are not executable", "tool": tool}
    return {"allowed": True, "reason": "Fixed recipe; human approval still required", "tool": tool, **RECIPES[tool]}


def require_allowed(tool):
    result = inspect_policy(tool)
    if not result["allowed"]:
        raise WorkflowError(result["reason"])
    return result


def scope_for_testing(bundle_id, bundle_hash, tool, runner_fingerprint):
    return {"kind": "testing_action", "bundle_id": bundle_id, "bundle_hash": bundle_hash, "tool": tool, "runner": runner_fingerprint}


class ToolBroker:
    def __init__(self, store, runner):
        self.store, self.runner = store, runner

    def execute(self, project, decision_id, scope, unit, files, tool):
        require_allowed(tool)
        if scope.get("tool") != tool:
            raise WorkflowError("Command recipe differs from the approved scope")
        live = self.store.project(project["id"])
        if scope.get("kind") == "testing_action":
            artifact = self.store.artifact(scope["bundle_id"])
            if artifact["project"] != live["id"] or live["data"].get("test_bundle") != artifact["id"] or artifact["hash"] != scope["bundle_hash"] or artifact["payload"]["files"] != files:
                raise WorkflowError("Execution files differ from the approved immutable bundle")
        elif scope.get("kind") == "development_evaluation":
            if unit not in {"a", "b"}:
                raise WorkflowError("Unknown development evaluation candidate")
            candidate = self.store.artifact(live["data"]["candidate_" + unit])
            if candidate["project"] != live["id"] or candidate["payload"]["files"] != files or candidate["payload"]["base"] != scope["baseline"] or candidate["payload"]["round"] != scope["round"]:
                raise WorkflowError("Execution files differ from the authorized candidate round")
            if any(live["data"].get(k) != scope[k] for k in ("plan_a", "plan_b")):
                raise WorkflowError("Implementation plans differ from the approved scope")
        else:
            raise WorkflowError("Unknown execution scope")
        if scope["runner"] != self.runner.fingerprint():
            raise WorkflowError("Sandbox environment changed; obtain a new human approval")
        execution = self.store.begin_execution(project, decision_id, scope, unit)
        result = self.runner.run(files, tool, execution)
        result = {**result, "execution_id": execution, "tree_hash": digest(files), "tool": tool, "runner": self.runner.fingerprint()}
        web_files = sorted(name for name in files if name.endswith((".html", ".css", ".js", ".mjs", ".svg")))
        if web_files:
            result["unchecked_web_files"] = web_files
            result["coverage_note"] = "Python checks do not parse or run web assets; inspect and test browser behavior separately."
        self.store.end_execution(execution, result)
        return result
