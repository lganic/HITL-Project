from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath


class WorkflowError(Exception):
    """An actionable, safe-to-display workflow error."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def uid(prefix):
    return prefix + "_" + uuid.uuid4().hex[:20]


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_text(value):
    # Prevent model-controlled ANSI/OSC terminal escape sequences.
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", str(value))


def validate_files(files, *, tests_only=False, implementation=False):
    if not isinstance(files, dict) or len(files) > 80:
        raise WorkflowError("Expected a bounded filename-to-text mapping")
    if sum(len(str(v).encode()) for v in files.values()) > 500_000:
        raise WorkflowError("Source tree exceeds the prototype's 500 KB limit")
    for name, content in files.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", name):
            raise WorkflowError("Invalid filename")
        path = PurePosixPath(name)
        if (path.is_absolute() or str(path) != name or any(p.startswith(".") for p in path.parts)
                or path.suffix not in {".py", ".md", ".json", ".toml", ".txt",
                                       ".html", ".css", ".js", ".mjs", ".svg"}):
            raise WorkflowError("Unsafe or unsupported source path: " + name)
        if not isinstance(content, str) or "\x00" in content:
            raise WorkflowError("Source content must be plain text")
        if tests_only and not (name.startswith("tests/test_") and name.endswith(".py")):
            raise WorkflowError("Test files must be tests/test_*.py")
        if implementation and (name.startswith("tests/") or name.startswith("hitl_se/")):
            raise WorkflowError("Implementations may not replace acceptance tests or control code")
    return files
