from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from .agents import Agents
from .config import DEFAULT, load_config
from .engine import Engine
from .providers import HTTPProvider
from .runner import DockerRunner
from .store import Store
from .util import WorkflowError, safe_text, validate_files


def display(value):
    print(safe_text(json.dumps(value, indent=2, ensure_ascii=False) if not isinstance(value, str) else value))


def make_engine(root):
    store = Store(root)
    config = load_config(store.root / "config.json")
    return Engine(store, Agents(HTTPProvider(config)), DockerRunner(config["runner"]), config.get("lease_seconds", 600))


def status(engine, project, full=False):
    p = engine.store.project(project)
    display(f"{p['name']} · iteration {p['iteration']} · {p['state']} · {p['status']}")
    if p["error"]:
        display("Error: " + p["error"])
    gate = engine.store.pending(project)
    if gate:
        proposal = gate["proposal"]
        display(f"\nHUMAN CHECKPOINT: {proposal['title']}\nGate: {gate['id']}\nDigest: {gate['digest']}")
        if full:
            display(proposal)
        else:
            for key in ("proposal", "rationale", "agent_rationales", "risks", "alternatives", "interventions", "policy", "execution_scope", "required_input"):
                if key in proposal:
                    display({key: proposal[key]})
            display("Evidence (use artifact ID to inspect full source/raw output):")
            for artifact in proposal["artifacts"]:
                display(f"  {artifact['artifact_id']}  {artifact['kind']}  {artifact['content'].get('summary', artifact['hash'][:12])}")
    return gate


def interactive_payload(state, action):
    if action == "info" or action == "reject":
        return {}
    if state == "dev.final" and action == "modify":
        return {"allow_evaluation": input("Renew the displayed bounded sandbox evaluation scope? [yes/no] ").strip() == "yes"}
    if action == "modify":
        return {}
    if state in {"design.direction", "design.decision", "dev.final"}:
        return {"selection": input("Select the displayed option/candidate ID: ").strip()}
    if state == "dev.plan_review":
        result = {"selection": input("Approach [A/B/custom]: ").strip()}
        if result["selection"] == "custom":
            result["approach"] = input("Corrected implementation approach: ").strip()
        result["allow_evaluation"] = input("Authorize the displayed bounded sandbox evaluation scope? [yes/no] ").strip() == "yes"
        return result
    if state == "deploy.manual":
        return {"status": input("Manual deployment status [deployed/deferred]: ").strip(), "record": input("What did you do, or why did you defer? ").strip()}
    if state == "review.feedback":
        notes = input("Demonstration and stakeholder notes: ").strip()
        new = input("New requirements (blank to close this iteration): ").strip()
        return {"demo_notes": notes, "new_requirements": new} if new else {"demo_notes": notes, "close": True}
    return {}


def export_source(engine, project, directory, tested=False):
    p = engine.store.project(project)
    key = "test_bundle" if tested else "main"
    if key not in p["data"]:
        raise WorkflowError("That source snapshot is not available yet")
    files = engine.payload(p, key)["files"]
    validate_files(files)
    root = Path(directory).resolve()
    if root.exists() and any(root.iterdir()):
        raise WorkflowError("Export destination must be empty")
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return str(root)


def console(engine, project, actor):
    token = engine.store.keyfile.read_text().strip()
    if not project:
        projects = engine.store.projects()
        for p in projects:
            display(f"{p['id']}  {p['name']}  {p['state']}")
        project = input("Project ID, or blank to create: ").strip()
        if not project:
            name = input("Project name: ").strip()
            goal = input("Stakeholder task / requirements: ").strip()
            project = engine.store.create(name, goal, token)
    display("Human control room. Agents stop at every checkpoint. No automatic approval.\nCommands: run, step, show, artifacts, artifact ID, compare, decide, recover, rework, log, export PATH, quit")
    while True:
        status(engine, project)
        try:
            line = input("hitl> ").strip()
            cmd, _, argument = line.partition(" ")
            if cmd in {"quit", "exit", "q"}:
                return
            if cmd == "run":
                engine.run(project, on_step=lambda state: display("Processing " + state))
            elif cmd == "step":
                engine.step(project)
            elif cmd == "show":
                status(engine, project, full=True)
            elif cmd == "artifacts":
                display(engine.store.artifacts(project))
            elif cmd == "artifact":
                artifact = engine.store.artifact(argument.strip())
                if artifact["project"] != project:
                    raise WorkflowError("Artifact belongs to a different project")
                display(artifact)
            elif cmd == "compare":
                display(engine.payload(engine.store.project(project), "candidate_diff")["diff"])
            elif cmd == "decide":
                gate = engine.store.pending(project)
                if not gate:
                    raise WorkflowError("Run to a human checkpoint first")
                action = input("Decision [approve/reject/modify/info/back]: ").strip()
                if action == "back":
                    continue
                feedback = input("Your reason, corrections, answers, or question: ").strip()
                payload = interactive_payload(gate["state"], action)
                result = engine.decide(project, gate["id"], gate["digest"], action, feedback, payload, actor, token)
                if action == "info":
                    display(engine.store.artifact(result))
            elif cmd == "recover":
                engine.recover(project, token)
            elif cmd == "rework":
                engine.source_rework(project, input("Source correction needed: ").strip(), token)
            elif cmd == "log":
                display(engine.store.events(project))
            elif cmd == "export":
                display(export_source(engine, project, argument.strip()))
            else:
                display("Use run, step, show, artifacts, artifact ID, compare, decide, recover, rework, log, export PATH, quit")
        except WorkflowError as exc:
            display("Stopped: " + str(exc))
        except (EOFError, KeyboardInterrupt):
            display("\nStopped. State is saved; resume with console.")
            return


def main(argv=None):
    parser = argparse.ArgumentParser(description="Human-governed software engineering prototype")
    parser.add_argument("--workspace", default=".hitl", help="persistent state/config directory")
    parser.add_argument("--actor", default=getpass.getuser())
    sub = parser.add_subparsers(dest="command", required=True)
    gui = sub.add_parser("gui", help="Open the graphical control room")
    gui.add_argument("--demo-workspace", default=".hitl-demo")
    gui.add_argument("--port", type=int, default=0)
    gui.add_argument("--no-browser", action="store_true")
    gui.add_argument("--live", action="store_true")
    sub.add_parser("init")
    sub.add_parser("list")
    p = sub.add_parser("new")
    p.add_argument("name")
    p.add_argument("--goal", required=True)
    p = sub.add_parser("console")
    p.add_argument("project", nargs="?")
    for cmd in ("run", "step", "inspect", "log", "artifacts", "recover", "compare"):
        p = sub.add_parser(cmd)
        p.add_argument("project")
    p = sub.add_parser("artifact")
    p.add_argument("identifier")
    p = sub.add_parser("decide")
    p.add_argument("project")
    for key in ("gate", "digest", "action", "feedback"):
        p.add_argument("--" + key, required=True)
    p.add_argument("--payload", default="{}")
    p = sub.add_parser("rework")
    p.add_argument("project")
    p.add_argument("--feedback", required=True)
    for cmd in ("export", "export-source"):
        p = sub.add_parser(cmd)
        p.add_argument("project")
        p.add_argument("destination")
        if cmd == "export-source":
            p.add_argument("--tested", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import launch
            launch(args.workspace, args.demo_workspace, args.actor, args.port, not args.no_browser, "live" if args.live else "demo")
            return 0
        if args.command == "init":
            store = Store(args.workspace)
            config = store.root / "config.json"
            if not config.exists():
                config.write_text(json.dumps(DEFAULT, indent=2) + "\n")
            display(f"Initialized {store.root}. Edit config.json, then run console. Human credential is private; never give it to agents.")
            return 0
        engine = make_engine(args.workspace)
        store = engine.store
        if args.command == "list":
            display([{k: p[k] for k in ("id", "name", "state", "status")} for p in store.projects()])
        elif args.command == "new":
            display(store.create(args.name, args.goal, store.keyfile.read_text().strip()))
        elif args.command == "console":
            console(engine, args.project, args.actor)
        elif args.command in {"run", "step"}:
            if args.command == "run":
                engine.run(args.project, on_step=lambda state: display("Processing " + state))
            else:
                engine.step(args.project)
            status(engine, args.project)
        elif args.command == "inspect":
            status(engine, args.project, full=True)
        elif args.command in {"log", "artifacts"}:
            display(getattr(store, "events" if args.command == "log" else "artifacts")(args.project))
        elif args.command == "artifact":
            display(store.artifact(args.identifier))
        elif args.command == "compare":
            display(engine.payload(store.project(args.project), "candidate_diff")["diff"])
        elif args.command == "decide":
            result = engine.decide(args.project, args.gate, args.digest, args.action, args.feedback, json.loads(args.payload), args.actor, store.keyfile.read_text().strip())
            display(result)
        elif args.command == "recover":
            engine.recover(args.project, store.keyfile.read_text().strip())
        elif args.command == "rework":
            engine.source_rework(args.project, args.feedback, store.keyfile.read_text().strip())
        elif args.command == "export-source":
            display(export_source(engine, args.project, args.destination, args.tested))
        elif args.command == "export":
            Path(args.destination).write_text(json.dumps(engine.export(args.project), indent=2) + "\n")
            display(args.destination)
        return 0
    except (WorkflowError, OSError, ValueError) as exc:
        display("Stopped: " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
