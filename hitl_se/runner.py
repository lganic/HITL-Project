from __future__ import annotations

import json
import os
import re
import threading
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .policy import require_allowed
from .util import WorkflowError, digest, validate_files

HARNESS = Path(__file__).with_name("check_harness.py")


def capture(command, *, timeout, limit, env=None):
    """Bound total captured bytes; terminate noisy processes instead of filling disk/RAM."""
    started = time.monotonic()
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, shell=False)
    output = {"stdout": bytearray(), "stderr": bytearray()}
    lock = threading.Lock()
    limit_hit = threading.Event()
    finished = {name: threading.Event() for name in output}

    def read_pipe(name, pipe):
        # Threads also work on Windows, where selectors cannot monitor pipes.
        try:
            while True:
                chunk = os.read(pipe.fileno(), 4096)
                if not chunk:
                    break
                with lock:
                    remaining = max(0, limit - sum(len(v) for v in output.values()))
                    output[name].extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        limit_hit.set()
                        break
        finally:
            pipe.close()
            finished[name].set()

    threads = [threading.Thread(target=read_pipe, args=(name, pipe), daemon=True)
               for name, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr))]
    for thread in threads:
        thread.start()
    stopped = None
    try:
        while not all(event.is_set() for event in finished.values()):
            if limit_hit.is_set():
                stopped = "output_limit"
                break
            if time.monotonic() - started > timeout:
                stopped = "timeout"
                break
            time.sleep(0.01)
        if limit_hit.is_set():
            stopped = "output_limit"
        if stopped and proc.poll() is None:
            proc.kill()
        # A process may close its streams before exiting; retain the same time budget.
        try:
            proc.wait(timeout=max(0.01, timeout - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            stopped = stopped or "timeout"
            proc.kill()
            proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=0.2)
    with lock:
        result = {name: bytes(value).decode("utf-8", "replace") for name, value in output.items()}
    return {"exit_code": proc.returncode, **result, "stopped": stopped, "duration_seconds": round(time.monotonic() - started, 4)}


def parse_result(raw):
    report = {}
    for line in raw["stdout"].splitlines():
        if line.startswith("HITL_RESULT="):
            try:
                report = json.loads(line[len("HITL_RESULT="):])
            except ValueError:
                report = {}
    return {**raw, "checks": report.get("checks", {}), "passed": raw["exit_code"] == 0 and not raw["stopped"] and report.get("passed") is True}


class DockerRunner:
    def __init__(self, config):
        self.config = config

    def fingerprint(self):
        return digest({"type": "docker", "config": self.config, "harness": HARNESS.read_text(), "isolation": "readonly,no-network,no-caps,nonroot,v1"})

    def cancel(self, execution_id):
        if not re.fullmatch(r"exec_[a-f0-9]{20}", execution_id):
            raise WorkflowError("Invalid execution identifier for sandbox cleanup")
        if not shutil.which("docker"):
            raise WorkflowError("Restore Docker before recovering an uncertain sandbox execution")
        result = subprocess.run(["docker", "rm", "-f", "hitl-" + execution_id], capture_output=True, text=True, timeout=10, check=False)
        if result.returncode and "No such container" not in result.stderr:
            raise WorkflowError("Could not stop the uncertain sandbox; check Docker before recovering")

    def run(self, files, tool, execution_id):
        require_allowed(tool)
        validate_files(files)
        if not shutil.which("docker"):
            raise WorkflowError("Docker is unavailable; install the sandbox. Host execution is never used as fallback")
        image = self.config["image"]
        if not re.fullmatch(r"[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}", image):
            raise WorkflowError("Configure a locally installed, digest-pinned Docker image")
        with tempfile.TemporaryDirectory(prefix="hitl-candidate-") as tmp:
            root = Path(tmp)
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                path.chmod(0o644)
            root.chmod(0o755)
            for directory in root.rglob("*"):
                if directory.is_dir():
                    directory.chmod(0o755)
            name = "hitl-" + execution_id
            command = ["docker", "run", "--rm", "--pull=never", "--name", name, "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534", "--memory=256m", "--memory-swap=256m", "--cpus=1", "--pids-limit=64", "--ulimit", "nofile=128:128", "--ulimit", "fsize=1048576:1048576", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--mount", f"type=bind,src={root},dst=/project,readonly", "--mount", f"type=bind,src={HARNESS.resolve()},dst=/harness.py,readonly", "--workdir=/project", "--env", "PYTHONDONTWRITEBYTECODE=1", "--entrypoint=python", image, "-I", "/harness.py", "/project", tool]
            try:
                raw = capture(command, timeout=self.config.get("timeout_seconds", 30), limit=self.config.get("output_limit_bytes", 65536))
            finally:
                # Killing the docker client alone need not stop the container.
                subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
            return parse_result(raw)
