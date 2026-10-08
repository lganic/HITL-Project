import unittest
from solution import normalize_whitespace

class IndependentTests(unittest.TestCase):
    def test_idempotent(self):
        for text in [" \thello\u2003world ", "", "a  b"]:
            result = normalize_whitespace(text)
            self.assertEqual(normalize_whitespace(result), result)
    def test_unicode_only(self):
        self.assertEqual(normalize_whitespace("\u00a0\u2003"), "")
