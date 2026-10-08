"""Control-room integration checks: real HTTP, persisted gates and fixture executions."""
import copy
import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile

from hitl_se.config import DEFAULT
from hitl_se.gui import ControlRoom, LocalServer
from hitl_se.util import WorkflowError
from examples.demo import default_payload


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = ControlRoom(self.temp.name+'/live', self.temp.name+'/demo', 'GUI reviewer')
        self.server = LocalServer(self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        headers = {'X-HITL-Session': self.app.token, **(headers or {})}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.server.origin+path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            data=response.read()
            return json.loads(data) if response.headers['Content-Type']=='application/json' else data

    def create(self):
        return self.request('/api/create', {'mode':'demo','name':'GUI normalizer','goal':'ignored for fixed fixture'})['project']

    def state(self, project):
        return self.request('/api/state?mode=demo&project='+project)

    def action(self, project, operation, **args):
        self.request('/api/action', {'mode':'demo','project':project,'operation':operation,**args})
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            job=self.state(project)['jobs'][project]
            if job['status']!='running':
                return job
            time.sleep(.02)
        self.fail('GUI operation did not finish')

    def decide(self, project, action='approve', payload=None, feedback='Reviewed proposal, source and measured evidence.'):
        gate=self.state(project)['gate']
        return self.action(project,'decide',gate=gate['id'],digest=gate['digest'],action=action,
                           feedback=feedback,actor='GUI reviewer',payload=default_payload(gate['state']) if payload is None else payload)

    def test_http_access_and_static_security(self):
        html=self.request('/')
        self.assertIn(b'Human checkpoint', html)
        for headers in [{'X-HITL-Session':''},{'Origin':'https://untrusted.example'},{'Host':'untrusted.example'}]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/state',headers=headers)
            self.assertEqual(caught.exception.code,403)
        self.assertIn(b'Content',self.request('/app.js'))
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/human.key')

    def test_full_human_driven_workflow_and_exports(self):
        project=self.create()
        modified=False
        seen=set()
        for _ in range(32):
            self.assertEqual(self.action(project,'run')['status'],'done')
            state=self.state(project)
            if state['project']['state']=='review.closed':
                break
            gate=state['gate']; seen.add(gate['state'])
            if gate['state']=='req.check':
                old=gate['id']
                self.assertEqual(self.decide(project,'info',{},'Explain the human approval boundary')['status'],'done')
                self.assertEqual(self.state(project)['gate']['id'],old)
            if gate['state']=='dev.final' and not modified:
                p=state['project']
                evidence=self.request('/api/artifact?mode=demo&project='+project+'&id='+p['data']['evidence_b'])
                self.assertFalse(evidence['payload']['passed'])
                self.assertEqual(self.decide(project,payload={'selection':'B'})['status'],'failed')
                self.assertEqual(self.state(project)['gate']['id'],gate['id'])
                self.assertEqual(self.decide(project,'modify',{'allow_evaluation':True},'Correct Unicode handling in candidate B and rerun checks.')['status'],'done')
                modified=True
            else:
                self.assertEqual(self.decide(project)['status'],'done')
        else:
            self.fail('Did not reach closure')
        self.assertTrue(modified)
        self.assertTrue({'req.check','design.direction','design.decision','dev.plan_review','dev.final','test.plan_review','test.policy','test.verify','deploy.manual','review.feedback'} <= seen)
        for kind in ['accepted','tested']:
            blob=self.request('/api/download?mode=demo&project='+project+'&kind='+kind)
            archive=zipfile.ZipFile(io.BytesIO(blob))
            self.assertIn('solution.py',archive.namelist())
            if kind=='tested': self.assertIn('tests/test_extra_invariants.py',archive.namelist())
        audit=self.request('/api/download?mode=demo&project='+project+'&kind=audit')
        self.assertEqual(audit['project']['state'],'review.closed')
        self.assertNotIn(self.app.store('demo').keyfile.read_text(),json.dumps(audit))
        self.assertTrue(all(d['actor']=='GUI reviewer' for d in audit['decisions']))

    def test_stale_gate_and_resume(self):
        project=self.create(); self.action(project,'run')
        gate=self.state(project)['gate']
        self.assertEqual(self.decide(project)['status'],'done')
        self.assertEqual(self.action(project,'decide',gate=gate['id'],digest=gate['digest'],action='approve',feedback='Repeat',actor='human',payload={})['status'],'failed')
        reopened=ControlRoom(self.temp.name+'/live',self.temp.name+'/demo')
        self.assertEqual(reopened.snapshot('demo',project)['project']['id'],project)
        self.assertEqual(reopened.snapshot('live')['projects'],[])

    def test_cross_project_artifact_rejected(self):
        a,b=self.create(),self.create()
        artifact=self.state(a)['project']['data']['main']
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/artifact?mode=demo&project='+b+'&id='+artifact)

    def test_config_validation_and_key_not_persisted(self):
        config=copy.deepcopy(DEFAULT)
        self.request('/api/config', {'config':config,'api_key':'private-test-key'})
        self.assertNotIn('private-test-key',self.app.store('live').root.joinpath('config.json').read_text())
        self.assertNotIn('private-test-key',json.dumps(self.request('/api/config')))
        self.assertEqual(self.app.engine('live').agents.provider.session_keys['HITL_API_KEY'],'private-test-key')
        config['runner']['kind']='host'
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/config',{'config':config})
        self.assertEqual(self.app.config()['runner']['kind'],'docker')

    def test_background_job_duplicate_and_config_guard(self):
        project=self.create()
        engine=self.app.engine('demo')
        release=threading.Event()
        started=threading.Event()
        original=engine.run
        def slow(*args,**kwargs):
            started.set(); release.wait(5)
            return original(*args,**kwargs)
        engine.run=slow
        self.app.engine=lambda mode:engine
        try:
            self.app.start('demo',project,'run',{})
            self.assertTrue(started.wait(1))
            self.assertEqual(self.state(project)['jobs'][project]['status'],'running')
            with self.assertRaises(WorkflowError): self.app.start('demo',project,'run',{})
            with self.assertRaises(WorkflowError): self.app.save_config(DEFAULT)
        finally:
            release.set()
            deadline=time.monotonic()+5
            while self.app.jobs[('demo',project)]['status']=='running' and time.monotonic()<deadline: time.sleep(.02)

    def test_rejection_rework_and_failed_job_recovery(self):
        project=self.create()
        self.action(project,'run')
        self.assertEqual(self.decide(project,'reject',{},'Clarify the Unicode acceptance cases')['status'],'done')
        self.assertEqual(self.state(project)['project']['state'],'req.collect')
        for _ in range(15):
            self.action(project,'run')
            state=self.state(project)
            if state['gate']['state']=='test.plan_review': break
            self.assertEqual(self.decide(project)['status'],'done')
        else: self.fail('Testing checkpoint not reached')
        self.assertEqual(self.action(project,'rework',feedback='Revise source to add stronger type handling')['status'],'done')
        self.assertEqual(self.state(project)['project']['state'],'dev.plan_a')
        self.assertIsNone(self.state(project)['gate'])
        # Simulate an interrupted provider operation using the engine's actual failure path.
        store=self.app.store('demo'); lease=store.claim(project,600)
        store.fail(lease,'Simulated provider timeout')
        self.assertEqual(self.action(project,'recover')['status'],'done')
        self.assertEqual(self.state(project)['project']['status'],'ready')

    def test_new_iteration_keeps_prior_artifacts(self):
        project=self.create()
        for _ in range(18):
            self.action(project,'run')
            gate=self.state(project)['gate']
            if gate['state']=='review.feedback': break
            self.assertEqual(self.decide(project)['status'],'done')
        else: self.fail('Review not reached')
        count=len(self.state(project)['artifacts'])
        payload={'demo_notes':'Reviewed the normalizer in the GUI.', 'new_requirements':'Preserve strict type handling in the next iteration.'}
        self.assertEqual(self.decide(project,payload=payload)['status'],'done')
        state=self.state(project)
        self.assertEqual(state['project']['iteration'],2)
        self.assertEqual(state['project']['state'],'req.collect')
        self.assertEqual(len(state['artifacts']),count)
