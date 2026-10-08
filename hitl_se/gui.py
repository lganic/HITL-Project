"""Local browser control room. All mutations go through the existing engine.

No remote hosting, dependencies, automatic approvals, or arbitrary tool endpoints.
The launch URL carries a short-lived browser capability, never the human key.
"""
from __future__ import annotations

import argparse
import copy
import getpass
import hmac
import io
import json
import secrets
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .agents import Agents
from .config import DEFAULT, load_config
from .engine import Engine
from .providers import HTTPProvider
from .runner import DockerRunner
from .store import Store
from .util import WorkflowError, validate_files
from .workflows import GATES, WORKFLOWS


class ControlRoom:
    def __init__(self, workspace='.hitl', demo_workspace='.hitl-demo', actor=None):
        self.roots = {'live': Path(workspace).resolve(), 'demo': Path(demo_workspace).resolve()}
        if self.roots['live'] == self.roots['demo']:
            raise WorkflowError('Live and demo workspaces must be different')
        self.actor = actor or getpass.getuser()
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.jobs = {}
        self.session_keys = {}
        self.stores = {}

    def store(self, mode):
        if mode not in self.roots:
            raise WorkflowError('Choose demo or live mode')
        with self.lock:
            if mode not in self.stores:
                self.stores[mode] = Store(self.roots[mode])
            return self.stores[mode]

    def config(self):
        store = self.store('live')
        path = store.root / 'config.json'
        if not path.exists():
            path.write_text(json.dumps(DEFAULT, indent=2) + '\n', encoding='utf-8')
        return load_config(path)

    def engine(self, mode):
        store = self.store(mode)
        if mode == 'demo':
            from .demo_fixtures import FixtureProvider, FixtureRunner
            return Engine(store, Agents(FixtureProvider()), FixtureRunner())
        config = self.config()
        return Engine(store, Agents(HTTPProvider(config, self.session_keys.copy())),
                      DockerRunner(config['runner']), config.get('lease_seconds', 600))

    def save_config(self, config, api_key=''):
        with self.lock:
            if any(j['status'] == 'running' for j in self.jobs.values()):
                raise WorkflowError('Wait for active work to stop before changing configuration')
            root = self.store('live').root
            temp = root / ('config-' + secrets.token_hex(8) + '.tmp')
            try:
                temp.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
                load_config(temp)
                if api_key and not config['provider'].get('api_key_env'):
                    raise WorkflowError('Set an API key variable name before entering a session key')
                temp.replace(root / 'config.json')
            finally:
                temp.unlink(missing_ok=True)
            if api_key:
                self.session_keys[config['provider']['api_key_env']] = api_key
        return {'saved': True}

    def snapshot(self, mode, project=None):
        store = self.store(mode)
        with self.lock:
            jobs = {p: copy.deepcopy(j) for (m, p), j in self.jobs.items() if m == mode}
        result = {'projects': store.projects(), 'jobs': jobs, 'actor': self.actor,
                  'workflows': WORKFLOWS, 'human_states': list(GATES), 'mode': mode}
        if project:
            # One read transaction gives a consistent project/gate/artifact view while workers advance.
            with store.connection() as conn:
                conn.execute('BEGIN')
                from .store import decode
                p = decode(conn.execute('SELECT * FROM projects WHERE id=?', (project,)).fetchone(), ('data',))
                row = conn.execute("SELECT * FROM gates WHERE project=? AND status='pending'", (project,)).fetchone()
                gate = decode(row, ('proposal',)) if row else None
                artifacts = [dict(r) for r in conn.execute('SELECT id,kind,version,producer,hash,iteration,created FROM artifacts WHERE project=? ORDER BY rowid', (project,))]
                events = [decode(r, ('payload',)) for r in conn.execute('SELECT * FROM events WHERE project=? ORDER BY id', (project,))]
            result.update(project=p, gate=gate, artifacts=artifacts, events=events)
        return result

    def create(self, mode, name, goal):
        store = self.store(mode)
        if mode == 'demo':
            from .demo_fixtures import GOAL
            goal = GOAL
        return {'project': store.create(name, goal, store.keyfile.read_text().strip())}

    def start(self, mode, project, operation, args):
        if operation not in {'run', 'step', 'decide', 'recover', 'rework'}:
            raise WorkflowError('Unknown operation')
        with self.lock:
            key = (mode, project)
            if self.jobs.get(key, {}).get('status') == 'running':
                raise WorkflowError('This project already has work in progress')
            engine = self.engine(mode)
            engine.store.project(project)
            job = {'status': 'running', 'operation': operation, 'state': None, 'error': None, 'result': None}
            self.jobs[key] = job
            def work():
                try:
                    credential = engine.store.keyfile.read_text().strip()
                    if operation == 'run':
                        def progress(state):
                            with self.lock:
                                job['state'] = state
                        value = engine.run(project, on_step=progress)
                        value = {'status': value['status']}
                    elif operation == 'step':
                        value = {'status': engine.step(project)['status']}
                    elif operation == 'decide':
                        value = engine.decide(project, args['gate'], args['digest'], args['action'],
                                              args['feedback'], args.get('payload', {}), args['actor'], credential)
                    elif operation == 'recover':
                        value = engine.recover(project, credential)
                    else:
                        value = engine.source_rework(project, args['feedback'], credential)
                    with self.lock:
                        job.update(status='done', result=value)
                except Exception as exc:
                    message = str(exc) if isinstance(exc, (WorkflowError, ValueError, KeyError)) else f'{type(exc).__name__}: operation stopped; inspect the local application'
                    with self.lock:
                        job.update(status='failed', error=message)
            # Non-daemon workers finish bounded operations if the server stops normally.
            threading.Thread(target=work, name=f'hitl-{operation}-{project}', daemon=False).start()
        return {'started': True}

    def download(self, mode, project, kind):
        engine = self.engine(mode)
        if kind == 'audit':
            return json.dumps(engine.export(project), indent=2, ensure_ascii=False).encode(), 'application/json', 'audit.json'
        if kind not in {'accepted', 'tested'}:
            raise WorkflowError('Unknown export')
        p = engine.store.project(project)
        key = 'test_bundle' if kind == 'tested' else 'main'
        if key not in p['data']:
            raise WorkflowError('That source snapshot is not available yet')
        files = engine.payload(p, key)['files']
        if not files:
            raise WorkflowError('No source files are available yet')
        validate_files(files)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return buf.getvalue(), 'application/zip', kind + '-source.zip'


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, app, port=0):
        self.app = app
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log request URLs/capabilities or user data.

    def send(self, data, content_type='application/json', status=200, filename=None):
        if not isinstance(data, bytes):
            data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        # Check Host even for static assets (DNS rebinding); no CORS is exposed.
        if self.headers.get('Host') != urlsplit(self.server.origin).netloc:
            self.send({'error': 'Invalid local host'}, status=403)
            return False
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin:
            self.send({'error': 'Cross-origin access denied'}, status=403)
            return False
        if urlsplit(self.path).path.startswith('/api/'):
            supplied = self.headers.get('X-HITL-Session', '')
            if not hmac.compare_digest(supplied, self.server.app.token):
                self.send({'error': 'Reopen the GUI from its launcher to connect'}, status=403)
                return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        try:
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            mode = query.get('mode', ['demo'])[0]
            project = query.get('project', [None])[0]
            app = self.server.app
            if url.path == '/api/state':
                self.send(app.snapshot(mode, project))
            elif url.path == '/api/config':
                self.send(app.config())
            elif url.path == '/api/artifact':
                artifact = app.store(mode).artifact(query['id'][0])
                if artifact['project'] != project:
                    raise WorkflowError('Artifact belongs to another project')
                self.send(artifact)
            elif url.path == '/api/download':
                data, mime, name = app.download(mode, project, query['kind'][0])
                self.send(data, mime, filename=name)
            elif url.path in {'/', '/app.js', '/style.css'}:
                name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[url.path]
                mime = {'/': 'text/html; charset=utf-8', '/app.js': 'text/javascript; charset=utf-8', '/style.css': 'text/css; charset=utf-8'}[url.path]
                self.send((Path(__file__).parent / 'web' / name).read_bytes(), mime)
            else:
                self.send({'error': 'Not found'}, status=404)
        except (WorkflowError, ValueError, KeyError, TypeError) as exc:
            self.send({'error': str(exc)}, status=400)
        except Exception:
            self.send({'error': 'Could not read application data'}, status=500)

    def do_POST(self):
        if not self.authorized():
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > 2_000_000:
                raise WorkflowError('Request must contain JSON smaller than 2 MB')
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise WorkflowError('Expected JSON')
            body = json.loads(self.rfile.read(size))
            app = self.server.app
            path = urlsplit(self.path).path
            if path == '/api/create':
                result = app.create(body['mode'], body['name'], body.get('goal', ''))
            elif path == '/api/action':
                result = app.start(body['mode'], body['project'], body['operation'], body)
            elif path == '/api/config':
                result = app.save_config(body['config'], body.get('api_key', ''))
            else:
                self.send({'error': 'Not found'}, status=404)
                return
            self.send(result)
        except (WorkflowError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.send({'error': str(exc)}, status=400)
        except Exception:
            self.send({'error': 'Operation could not be started'}, status=500)


def launch(workspace='.hitl', demo_workspace='.hitl-demo', actor=None, port=0, open_browser=True, mode='demo'):
    app = ControlRoom(workspace, demo_workspace, actor)
    server = LocalServer(app, port)
    url = server.origin + '/#session=' + app.token + '&mode=' + mode
    print('HITL control room: ' + url, flush=True)
    print('Keep this launcher open. Closing the browser preserves all progress.', flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping GUI; active bounded work will finish.', flush=True)
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description='Local HITL graphical control room')
    parser.add_argument('--workspace', default='.hitl')
    parser.add_argument('--demo-workspace', default='.hitl-demo')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    launch(args.workspace, args.demo_workspace, port=args.port, open_browser=not args.no_browser,
           mode='live' if args.live else 'demo')


if __name__ == '__main__':
    main()
