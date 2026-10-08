from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from .util import WorkflowError, canonical, digest, now, uid

DDL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL, iteration INTEGER NOT NULL,
 state TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
 data TEXT NOT NULL, lease_token TEXT, lease_until REAL, error TEXT);
CREATE TABLE IF NOT EXISTS artifacts(
 id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id), iteration INTEGER NOT NULL,
 kind TEXT NOT NULL, version INTEGER NOT NULL, producer TEXT NOT NULL,
 payload TEXT NOT NULL, hash TEXT NOT NULL, created TEXT NOT NULL,
 UNIQUE(project,kind,version));
CREATE TABLE IF NOT EXISTS gates(
 id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id), state TEXT NOT NULL,
 proposal TEXT NOT NULL, digest TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_gate ON gates(project) WHERE status='pending';
CREATE TABLE IF NOT EXISTS decisions(
 id TEXT PRIMARY KEY, gate_id TEXT NOT NULL REFERENCES gates(id), actor TEXT NOT NULL,
 action TEXT NOT NULL, feedback TEXT NOT NULL, payload TEXT NOT NULL,
 proposal_digest TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL REFERENCES projects(id),
 state TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS executions(
 id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id), state TEXT NOT NULL,
 decision_id TEXT NOT NULL REFERENCES decisions(id), scope_hash TEXT NOT NULL,
 unit TEXT NOT NULL, status TEXT NOT NULL, result TEXT, created TEXT NOT NULL,
 UNIQUE(decision_id,unit));
"""


def decode(row, fields=()):
    if row is None:
        raise WorkflowError("Record not found")
    result = dict(row)
    for field in fields:
        if result[field] is not None:
            result[field] = json.loads(result[field])
    return result


class Store:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "state.sqlite3"
        self.keyfile = self.root / "human.key"
        with self.connection() as conn:
            conn.executescript(DDL)
            conn.execute("CREATE TRIGGER IF NOT EXISTS immutable_gate_proposal BEFORE UPDATE OF proposal,digest,project,state ON gates BEGIN SELECT RAISE(ABORT, 'immutable checkpoint proposal'); END")
            for table in ("artifacts", "decisions", "events"):
                for op in ("UPDATE", "DELETE"):
                    conn.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{op} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable audit record'); END")
            if conn.execute("SELECT value FROM meta WHERE key='human_hash'").fetchone() is None:
                token = secrets.token_urlsafe(32)
                fd = os.open(self.keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(token)
                conn.execute("INSERT INTO meta VALUES ('human_hash', ?)", (hashlib.sha256(token.encode()).hexdigest(),))
                conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
        os.chmod(self.db, 0o600)

    @contextlib.contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def authenticate(self, token):
        with self.connection() as conn:
            expected = conn.execute("SELECT value FROM meta WHERE key='human_hash'").fetchone()[0]
        if not isinstance(token, str) or not hmac.compare_digest(expected, hashlib.sha256(token.encode()).hexdigest()):
            raise WorkflowError("Human control credential is required")

    def _event(self, conn, project, state, kind, payload):
        conn.execute("INSERT INTO events(project,state,type,payload,created) VALUES(?,?,?,?,?)", (project, state, kind, canonical(payload), now()))

    def _artifact(self, conn, project, iteration, kind, payload, producer):
        identifier = uid("art")
        version = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM artifacts WHERE project=? AND kind=?", (project, kind)).fetchone()[0]
        conn.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?)", (identifier, project, iteration, kind, version, producer, canonical(payload), digest(payload), now()))
        return identifier

    def create(self, name, goal, token):
        self.authenticate(token)
        if not name.strip() or not goal.strip():
            raise WorkflowError("Project name and stakeholder goal are required")
        project = uid("prj")
        with self.transaction() as conn:
            conn.execute("INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?,?)", (project, name, goal, 1, "req.collect", "ready", 0, "{}", None, None, None))
            main = self._artifact(conn, project, 1, "main", {"files": {}, "parent": None}, "human")
            data = {"main": main, "seed": goal, "feedback": [], "dev_round": 1}
            conn.execute("UPDATE projects SET data=? WHERE id=?", (canonical(data), project))
            self._event(conn, project, "req.collect", "project_created", {"name": name})
        return project

    def project(self, project):
        with self.connection() as conn:
            return decode(conn.execute("SELECT * FROM projects WHERE id=?", (project,)).fetchone(), ("data",))

    def projects(self):
        with self.connection() as conn:
            return [decode(r, ("data",)) for r in conn.execute("SELECT * FROM projects ORDER BY rowid")]

    def artifact(self, identifier):
        with self.connection() as conn:
            item = decode(conn.execute("SELECT * FROM artifacts WHERE id=?", (identifier,)).fetchone(), ("payload",))
        if digest(item["payload"]) != item["hash"]:
            raise WorkflowError("Artifact integrity check failed")
        return item

    def artifacts(self, project):
        with self.connection() as conn:
            return [dict(r) for r in conn.execute("SELECT id,kind,version,producer,hash,iteration,created FROM artifacts WHERE project=? ORDER BY rowid", (project,))]

    def events(self, project):
        with self.connection() as conn:
            return [decode(r, ("payload",)) for r in conn.execute("SELECT * FROM events WHERE project=? ORDER BY id", (project,))]

    def executions(self, project):
        with self.connection() as conn:
            return [decode(r, ("result",)) for r in conn.execute("SELECT * FROM executions WHERE project=? ORDER BY rowid", (project,))]

    def pending(self, project):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM gates WHERE project=? AND status='pending'", (project,)).fetchone()
            return decode(row, ("proposal",)) if row else None

    def gates(self, project):
        with self.connection() as conn:
            return [decode(row, ("proposal",)) for row in conn.execute("SELECT * FROM gates WHERE project=? ORDER BY rowid", (project,))]

    def decisions(self, project):
        with self.connection() as conn:
            return [decode(r, ("payload",)) for r in conn.execute("SELECT d.* FROM decisions d JOIN gates g ON d.gate_id=g.id WHERE g.project=? ORDER BY d.rowid", (project,))]

    def claim(self, project, lease_seconds):
        with self.transaction() as conn:
            p = decode(conn.execute("SELECT * FROM projects WHERE id=?", (project,)).fetchone(), ("data",))
            if p["status"] != "ready":
                raise WorkflowError(f"Project is {p['status']}; inspect the gate or recover explicitly")
            token = uid("op")
            conn.execute("UPDATE projects SET status='running',lease_token=?,lease_until=?,revision=revision+1 WHERE id=?", (token, time.time() + lease_seconds, project))
            self._event(conn, project, p["state"], "step_started", {"operation": token})
            p.update(status="running", lease_token=token, revision=p["revision"] + 1)
            return p

    def finish(self, p, next_state, data, outputs, iteration=None):
        with self.transaction() as conn:
            live = conn.execute("SELECT lease_token,status FROM projects WHERE id=?", (p["id"],)).fetchone()
            if live[0] != p["lease_token"] or live[1] != "running":
                raise WorkflowError("Stale operation cannot commit")
            refs = {}
            for key, (kind, payload, producer) in outputs.items():
                refs["@out:" + key] = self._artifact(conn, p["id"], p["iteration"], kind, payload, producer)
            def resolve(value):
                if isinstance(value, str):
                    return refs.get(value, value)
                if isinstance(value, list):
                    return [resolve(v) for v in value]
                if isinstance(value, dict):
                    return {k: resolve(v) for k, v in value.items()}
                return value
            data = resolve(data)
            conn.execute("UPDATE projects SET state=?,status='ready',data=?,iteration=?,revision=revision+1,lease_token=NULL,lease_until=NULL,error=NULL WHERE id=?", (next_state, canonical(data), iteration or p["iteration"], p["id"]))
            self._event(conn, p["id"], p["state"], "step_completed", {"next": next_state, "artifacts": refs})

    def fail(self, p, error):
        with self.transaction() as conn:
            result = conn.execute("UPDATE projects SET status='failed',error=?,revision=revision+1 WHERE id=? AND lease_token=?", (error, p["id"], p["lease_token"]))
            if result.rowcount:
                self._event(conn, p["id"], p["state"], "step_failed", {"error": error})

    def open_gate(self, p, proposal):
        with self.transaction() as conn:
            live = conn.execute("SELECT status,revision FROM projects WHERE id=?", (p["id"],)).fetchone()
            if live[0] != "ready" or live[1] != p["revision"]:
                raise WorkflowError("Project changed while opening the checkpoint")
            gate = uid("gate")
            conn.execute("INSERT INTO gates VALUES(?,?,?,?,?,?,?)", (gate, p["id"], p["state"], canonical(proposal), digest(proposal), "pending", now()))
            conn.execute("UPDATE projects SET status='waiting',revision=revision+1 WHERE id=?", (p["id"],))
            self._event(conn, p["id"], p["state"], "gate_opened", {"gate": gate, "digest": digest(proposal)})
        return self.pending(p["id"])

    def resolve(self, p, gate_id, proposal_digest, action, feedback, payload, actor, data, next_state, token, iteration=None):
        self.authenticate(token)
        with self.transaction() as conn:
            gate = decode(conn.execute("SELECT * FROM gates WHERE id=? AND project=?", (gate_id, p["id"])).fetchone(), ("proposal",))
            live = conn.execute("SELECT revision,status,state FROM projects WHERE id=?", (p["id"],)).fetchone()
            if gate["status"] != "pending" or gate["digest"] != proposal_digest or live[0] != p["revision"] or live[1] != "waiting" or live[2] != gate["state"]:
                raise WorkflowError("Stale, resolved, or mismatched human checkpoint")
            decision = uid("dec")
            conn.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?)", (decision, gate_id, actor, action, feedback, canonical(payload), proposal_digest, now()))
            for key, value in list(data.items()):
                if value == "@decision":
                    data[key] = decision
            conn.execute("UPDATE gates SET status='resolved' WHERE id=?", (gate_id,))
            conn.execute("UPDATE projects SET status='ready',state=?,data=?,iteration=?,revision=revision+1,error=NULL WHERE id=?", (next_state, canonical(data), iteration or p["iteration"], p["id"]))
            self._event(conn, p["id"], p["state"], "human_decision", {"decision": decision, "action": action, "feedback": feedback, "payload": payload, "actor": actor, "next": next_state})
            return decision

    def information(self, p, gate, feedback, response, actor, token):
        self.authenticate(token)
        with self.transaction() as conn:
            row = conn.execute("SELECT status,digest FROM gates WHERE id=?", (gate["id"],)).fetchone()
            if row[0] != "pending" or row[1] != gate["digest"]:
                raise WorkflowError("Checkpoint changed during explanation")
            art = self._artifact(conn, p["id"], p["iteration"], "explanation", {"gate_id": gate["id"], "question": feedback, "response": response}, "explainer")
            decision = uid("dec")
            conn.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?)", (decision, gate["id"], actor, "info", feedback, canonical({"artifact": art}), gate["digest"], now()))
            self._event(conn, p["id"], p["state"], "information_requested", {"question": feedback, "explanation": art})
            return art

    def begin_execution(self, p, decision_id, scope, unit):
        with self.transaction() as conn:
            live = conn.execute("SELECT state,status,lease_token FROM projects WHERE id=?", (p["id"],)).fetchone()
            if tuple(live) != (p["state"], "running", p["lease_token"]):
                raise WorkflowError("Execution needs an active workflow lease")
            row = conn.execute("SELECT d.action,g.state,g.project,g.proposal FROM decisions d JOIN gates g ON d.gate_id=g.id WHERE d.id=?", (decision_id,)).fetchone()
            if not row or row[2] != p["id"]:
                raise WorkflowError("Execution requires a human decision")
            accepted = ((p["state"] == "test.execute" and row[1] == "test.policy" and row[0] == "approve") or
                        (p["state"] == "dev.evaluate" and ((row[1] == "dev.plan_review" and row[0] == "approve") or (row[1] == "dev.final" and row[0] == "modify"))))
            if not accepted or json.loads(row[3]).get("execution_scope") != scope:
                raise WorkflowError("Human permission does not match the execution scope")
            identifier = uid("exec")
            try:
                conn.execute("INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?)", (identifier, p["id"], p["state"], decision_id, digest(scope), unit, "running", None, now()))
            except sqlite3.IntegrityError:
                raise WorkflowError("This execution permission has already been used") from None
            self._event(conn, p["id"], p["state"], "execution_started", {"execution": identifier, "decision": decision_id, "scope": scope, "unit": unit})
            return identifier

    def end_execution(self, identifier, result):
        with self.transaction() as conn:
            conn.execute("UPDATE executions SET status='done',result=? WHERE id=? AND status='running'", (canonical(result), identifier))

    def recover(self, project, token, next_state):
        self.authenticate(token)
        with self.transaction() as conn:
            p = decode(conn.execute("SELECT * FROM projects WHERE id=?", (project,)).fetchone(), ("data",))
            if p["status"] not in {"failed", "running"}:
                raise WorkflowError("Only a failed or interrupted operation can be recovered")
            if p["status"] == "running" and (p["lease_until"] or 0) > time.time():
                raise WorkflowError("The worker lease is still live; wait for expiry before recovery")
            conn.execute("UPDATE executions SET status='uncertain' WHERE project=? AND status='running'", (project,))
            conn.execute("UPDATE projects SET state=?,status='ready',lease_token=NULL,lease_until=NULL,error=NULL,revision=revision+1 WHERE id=?", (next_state, project))
            self._event(conn, project, p["state"], "human_recovery", {"next": next_state})

    def rework(self, project, feedback, token):
        self.authenticate(token)
        with self.transaction() as conn:
            p = decode(conn.execute("SELECT * FROM projects WHERE id=?", (project,)).fetchone(), ("data",))
            if not p["state"].startswith("test.") or p["status"] == "running":
                raise WorkflowError("Source rework is available only in stopped testing states")
            conn.execute("UPDATE gates SET status='superseded' WHERE project=? AND status='pending'", (project,))
            d = p["data"]
            d["feedback"].append({"state": p["state"], "action": "source_rework", "text": feedback})
            conn.execute("UPDATE projects SET state='dev.plan_a',status='ready',data=?,revision=revision+1,lease_token=NULL,lease_until=NULL,error=NULL WHERE id=?", (canonical(d), project))
            self._event(conn, project, p["state"], "human_source_rework", {"feedback": feedback, "next": "dev.plan_a"})
