from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from .util import WorkflowError, canonical


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class HTTPProvider:
    """OpenAI-compatible Chat Completions transport; works with local servers too."""

    def __init__(self, config, session_keys=None):
        self.config = config
        self.session_keys = session_keys or {}

    def complete(self, role, messages, schema):
        settings = dict(self.config["provider"])
        settings.update(self.config.get("roles", {}).get(role, {}))
        base = settings["base_url"].rstrip("/")
        parts = urllib.parse.urlsplit(base)
        if parts.username or parts.password or parts.query or parts.fragment:
            raise WorkflowError("Provider URL must not contain credentials, query or fragment")
        if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise WorkflowError("Remote providers require HTTPS")
        model = settings.get("model", "")
        if not model or model == "SET_YOUR_MODEL":
            raise WorkflowError("Configure a model before running agents")
        key_name = settings.get("api_key_env", "")
        key = self.session_keys.get(key_name, os.environ.get(key_name, "")) if key_name else ""
        if key_name and not key:
            raise WorkflowError(f"Set the configured API key environment variable: {key_name}")
        body = {"model": model, "messages": messages, "stream": False}
        if settings.get("json_mode", True):
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        request = urllib.request.Request(base + "/chat/completions", canonical(body).encode(), headers, method="POST")
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=settings.get("timeout_seconds", 120)) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise WorkflowError("Provider response exceeds 1 MB")
            envelope = json.loads(raw)
            choice = envelope["choices"][0]
            if choice.get("finish_reason") not in {None, "stop"}:
                raise WorkflowError("Provider did not return a complete text response")
            content = choice["message"]["content"]
            result = json.loads(content)
            if not isinstance(result, dict):
                raise WorkflowError("Provider must return a JSON object")
            metadata = {"provider": parts.hostname, "model": model, "usage": envelope.get("usage", {})}
            return result, metadata
        except urllib.error.HTTPError as exc:
            # Never include response bodies or headers, which may echo secrets.
            raise WorkflowError(f"Provider HTTP {exc.code}; check configuration or retry explicitly") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise WorkflowError("Provider connection failed or timed out; retry explicitly") from None
        except (ValueError, KeyError, TypeError, IndexError):
            raise WorkflowError("Provider returned invalid structured JSON") from None
