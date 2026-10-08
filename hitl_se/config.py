from __future__ import annotations

import json
from pathlib import Path
from .util import WorkflowError

DEFAULT = {
    "provider": {"base_url": "https://api.openai.com/v1", "model": "SET_YOUR_MODEL", "api_key_env": "HITL_API_KEY", "timeout_seconds": 120, "json_mode": True},
    "roles": {},
    "runner": {"kind": "docker", "image": "SET_A_LOCAL_IMAGE_AT_SHA256_DIGEST", "timeout_seconds": 30, "output_limit_bytes": 65536},
    "lease_seconds": 600,
}


def load_config(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise WorkflowError("Cannot read configuration JSON") from exc
    if not isinstance(value, dict) or set(value) - set(DEFAULT) or not {"provider", "runner"}.issubset(value):
        raise WorkflowError("Configuration requires provider and runner; see config.example.json")
    if not isinstance(value["provider"], dict) or not isinstance(value["runner"], dict) or not isinstance(value.get("roles", {}), dict):
        raise WorkflowError("provider, runner and roles must be objects")
    if value["runner"].get("kind") != "docker":
        raise WorkflowError("The live application supports only the Docker sandbox")
    if not 30 <= value.get("lease_seconds", 600) <= 3600:
        raise WorkflowError("lease_seconds must be between 30 and 3600")
    timeouts = [value["provider"].get("timeout_seconds", 120)]
    for settings in value.get("roles", {}).values():
        if not isinstance(settings, dict):
            raise WorkflowError("Each role override must be an object")
        timeouts.append(settings.get("timeout_seconds", timeouts[0]))
    execution_timeout = value["runner"].get("timeout_seconds", 30)
    if any(type(t) not in (int, float) or not 1 <= t <= 300 for t in [*timeouts, execution_timeout]):
        raise WorkflowError("Provider and execution timeouts must be 1–300 seconds")
    if value.get("lease_seconds", 600) < 2 * max(*timeouts, execution_timeout) + 30:
        raise WorkflowError("Lease must exceed two sequential operations plus a 30-second recovery margin")
    output_limit = value["runner"].get("output_limit_bytes", 65536)
    if type(output_limit) is not int or not 1024 <= output_limit <= 1_048_576:
        raise WorkflowError("output_limit_bytes must be between 1024 and 1048576")
    return value
