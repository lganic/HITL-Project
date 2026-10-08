"""Trusted, fixed sandbox entrypoint. Invoked only inside sandbox/fixture runner."""
import ast
import json
import pathlib
import sys
import unittest


def run(root, tool):
    root = pathlib.Path(root)
    checks = {}
    if tool in {"python_checks", "static_analysis"}:
        errors, warnings = [], []
        for path in sorted(root.rglob("*.py")):
            rel = str(path.relative_to(root))
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        name = ast.unparse(node.func)
                        if name in {"eval", "exec", "os.system", "subprocess.run", "subprocess.Popen", "__import__"}:
                            warnings.append({"file": rel, "line": node.lineno, "risk": name})
            except (SyntaxError, UnicodeError) as exc:
                errors.append({"file": rel, "error": str(exc)})
        checks["static_analysis"] = {"passed": not errors, "errors": errors, "warnings": warnings}
    if tool in {"python_checks", "python_tests"}:
        sys.path.insert(0, str(root))
        try:
            suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
            result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(suite)
            checks["python_tests"] = {"passed": result.wasSuccessful() and result.testsRun > 0, "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}
        except Exception as exc:
            checks["python_tests"] = {"passed": False, "tests_run": 0, "error": str(exc)}
    if not checks:
        raise ValueError("Unknown fixed recipe")
    report = {"passed": all(v["passed"] for v in checks.values()), "checks": checks}
    print("HITL_RESULT=" + json.dumps(report), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1], sys.argv[2]))
