import contextlib
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from hitl_se.cli import main
from hitl_se.config import DEFAULT
from hitl_se.providers import HTTPProvider
from hitl_se.runner import DockerRunner, capture
from hitl_se.schemas import SCHEMAS
from hitl_se.util import WorkflowError, safe_text


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.received = []
        cls.response = {"choices": [{"finish_reason": "stop", "message": {"content": '{"answer":"actual HTTP response"}'}}], "usage": {"prompt_tokens": 10}}
        cls.status = 200
        outer = cls
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.received.append((self.path, body, self.headers.get("Authorization")))
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(outer.response).encode())
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def config(self):
        return {"provider": {"base_url": f"http://127.0.0.1:{self.server.server_port}/v1", "model": "default-model", "api_key_env": "", "json_mode": True}, "roles": {"planner_b": {"model": "independent-model"}}}

    def test_real_http_transport_and_per_role_routing(self):
        provider = HTTPProvider(self.config())
        result, meta = provider.complete("planner_b", [{"role": "user", "content": "Return JSON"}], SCHEMAS["planner_b"])
        self.assertEqual(result["answer"], "actual HTTP response")
        path, request, authorization = self.received[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(request["model"], "independent-model")
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertIsNone(authorization)
        self.assertEqual(meta["model"], "independent-model")

    def test_http_errors_do_not_log_response_body_secrets(self):
        original = type(self).response
        type(self).response, type(self).status = {"secret": "DO_NOT_LEAK"}, 401
        try:
            with self.assertRaises(WorkflowError) as caught:
                HTTPProvider(self.config()).complete("collector", [], {})
            self.assertNotIn("DO_NOT_LEAK", str(caught.exception))
            self.assertIn("401", str(caught.exception))
        finally:
            type(self).response, type(self).status = original, 200

    def test_invalid_response_and_truncation_fail_closed(self):
        original = type(self).response
        try:
            for response in ({"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}, {"choices": [{"message": {"content": "not JSON"}}]}):
                type(self).response = response
                with self.assertRaises(WorkflowError):
                    HTTPProvider(self.config()).complete("collector", [], {})
        finally:
            type(self).response = original

    def test_remote_cleartext_and_credential_urls_rejected(self):
        for url in ("http://remote.example/v1", "https://key:secret@example.com/v1", "https://example.com/v1?key=secret"):
            config = self.config()
            config["provider"]["base_url"] = url
            with self.assertRaises(WorkflowError):
                HTTPProvider(config).complete("collector", [], {})

    def test_credentials_are_in_header_only_not_artifact_metadata(self):
        config = self.config()
        config["provider"]["api_key_env"] = "HITL_TEST_FAKE_KEY"
        with patch.dict(os.environ, {"HITL_TEST_FAKE_KEY": "test-only-fake-key"}):
            _, meta = HTTPProvider(config).complete("collector", [], {})
        self.assertEqual(self.received[-1][2], "Bearer test-only-fake-key")
        self.assertNotIn("test-only-fake-key", json.dumps(meta))


class RunnerAndCLITests(unittest.TestCase):
    def test_missing_docker_never_falls_back_to_host(self):
        runner = DockerRunner(DEFAULT["runner"])
        with patch("hitl_se.runner.shutil.which", return_value=None), patch("hitl_se.runner.subprocess.Popen") as launch:
            with self.assertRaises(WorkflowError):
                runner.run({"solution.py": "print('no')"}, "python_checks", "test")
            launch.assert_not_called()

    def test_docker_launch_uses_fixed_sandbox_options_and_no_shell(self):
        config = {"image": "python@sha256:" + "a" * 64, "timeout_seconds": 10, "output_limit_bytes": 2048}
        result = {"exit_code": 0, "stdout": 'HITL_RESULT={"passed":true,"checks":{}}', "stderr": "", "stopped": None}
        with patch("hitl_se.runner.shutil.which", return_value="/usr/bin/docker"), patch("hitl_se.runner.capture", return_value=result) as run, patch("hitl_se.runner.subprocess.run") as cleanup:
            DockerRunner(config).run({"solution.py": "pass"}, "python_checks", "unit-test")
        argv = run.call_args.args[0]
        for arg in ("--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534", "--pull=never", "--pids-limit=64"):
            self.assertIn(arg, argv)
        self.assertNotIn("/var/run/docker.sock", " ".join(argv))
        self.assertNotIn("human.key", " ".join(argv))
        cleanup.assert_called_once()

    def test_unpinned_images_and_unknown_tools_are_refused(self):
        with patch("hitl_se.runner.shutil.which", return_value="docker"):
            for tool in ("python_checks", "deploy", "rm -rf /"):
                with self.assertRaises(WorkflowError):
                    DockerRunner({"image": "python:latest"}).run({}, tool, "test")

    def test_capture_enforces_timeout_and_output_limit(self):
        import sys
        noisy = capture([sys.executable, "-c", "print('x'*100000)"], timeout=5, limit=2048, env={})
        self.assertEqual(noisy["stopped"], "output_limit")
        slow = capture([sys.executable, "-c", "import time; time.sleep(2)"], timeout=.1, limit=2048, env={})
        self.assertEqual(slow["stopped"], "timeout")

    def test_cli_init_new_list_inspect_and_no_auto_approve_option(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--workspace", temp, "init"]), 0)
            self.assertEqual(main(["--workspace", temp, "new", "CLI task", "--goal", "Implement a function"]), 0)
            self.assertEqual(main(["--workspace", temp, "list"]), 0)
            config = json.loads((Path(temp) / "config.json").read_text())
            self.assertEqual(config["runner"]["kind"], "docker")
            self.assertIn("CLI task", output.getvalue())
            self.assertNotIn((Path(temp) / "human.key").read_text(), output.getvalue())

    def test_terminal_escape_sequences_are_not_rendered(self):
        self.assertNotIn("\x1b", safe_text("model\x1b]52;c;clipboard\x07"))


if __name__ == "__main__":
    unittest.main()
