"""Live-model citation corrections must preserve evidence provenance."""
import json
import unittest

from hitl_se.agents import Agents
from hitl_se.util import WorkflowError


class CitationProvider:
    def __init__(self, corrected):
        self.calls = []
        self.corrected = corrected

    def complete(self, role, messages, schema):
        self.calls.append(messages)
        ref = 'REQ-1' if len(self.calls) == 1 or not self.corrected else 'pattern:pure-library'
        return {
            'summary': 'Design options', 'rationale': 'Compare architecture costs',
            'risks': [], 'alternatives': [],
            'options': [
                {'id': 'library', 'description': 'Pure function library',
                 'tradeoffs': ['Simple interface'], 'evidence': [ref]},
                {'id': 'service', 'description': 'API service',
                 'tradeoffs': ['Network overhead'], 'evidence': ['art_srs123']},
            ], 'recommendation': 'library',
        }, {'model': 'test-model'}


class AgentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            'srs': {'artifact_id': 'art_srs123', 'content': {'requirements': [{'id': 'REQ-1'}]}},
            'observations': [{'results': [{'id': 'pattern:pure-library'}]}],
        }

    def test_model_corrects_requirement_label_to_supplied_pattern_id(self):
        provider = CitationProvider(corrected=True)
        result = Agents(provider).run('architect', self.context)
        self.assertEqual(len(provider.calls), 2)
        self.assertIn('pattern:pure-library', provider.calls[0][0]['content'])
        self.assertNotIn('REQ-1', json.dumps(result['options'][0]['evidence']))
        self.assertEqual(result['options'][0]['evidence'], ['pattern:pure-library'])
        self.assertEqual(result['_invocation']['attempts'], 2)
        self.assertEqual(result['_invocation']['evidence_ids'], ['art_srs123', 'pattern:pure-library'])
        self.assertEqual(json.loads(provider.calls[1][1]['content']), self.context)

    def test_persistent_unknown_citation_remains_rejected(self):
        provider = CitationProvider(corrected=False)
        with self.assertRaisesRegex(WorkflowError, 'unknown evidence artifact'):
            Agents(provider).run('architect', self.context)
        self.assertEqual(len(provider.calls), 2)


if __name__ == '__main__':
    unittest.main()
