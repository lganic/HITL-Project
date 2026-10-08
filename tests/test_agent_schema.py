"""Live implementation agents must nest source paths under files."""
import json
import unittest

from hitl_se.agents import Agents
from hitl_se.util import WorkflowError


class FlatFileProvider:
    def __init__(self, corrected):
        self.corrected = corrected
        self.calls = []

    def complete(self, role, messages, schema):
        self.calls.append(messages)
        result = {
            'summary': 'Battleship implementation',
            'rationale': 'Implements the approved approach',
            'risks': [], 'alternatives': [],
            'files': {'battleship/game.py': 'def play():\n    return "ready"\n'},
        }
        if len(self.calls) == 1 or not self.corrected:
            result['battleship/game.py'] = result['files']['battleship/game.py']
        return result, {'model': 'test-model'}


class AgentSchemaTests(unittest.TestCase):
    def test_misplaced_file_key_is_regenerated_inside_files(self):
        provider = FlatFileProvider(corrected=True)
        result = Agents(provider).run('implementer_a', {'approved_approach': 'Build Battleship'})
        self.assertEqual(len(provider.calls), 2)
        self.assertIn('TOP_LEVEL_KEYS', provider.calls[0][0]['content'])
        self.assertIn('files', json.loads(provider.calls[0][0]['content'].split('TOP_LEVEL_KEYS:\n')[1].split('\n')[0]))
        self.assertNotIn('battleship/game.py', result.keys())
        self.assertEqual(result['files']['battleship/game.py'], 'def play():\n    return "ready"\n')
        self.assertEqual(result['_invocation']['attempts'], 2)

    def test_repeated_misplaced_file_key_still_fails(self):
        provider = FlatFileProvider(corrected=False)
        with self.assertRaisesRegex(WorkflowError, 'unexpected field battleship/game.py'):
            Agents(provider).run('implementer_a', {})
        self.assertEqual(len(provider.calls), 2)


if __name__ == '__main__':
    unittest.main()
