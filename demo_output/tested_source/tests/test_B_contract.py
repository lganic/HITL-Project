import unittest
from solution import normalize_whitespace

class BoundaryTests(unittest.TestCase):
    def test_unicode_separator(self):
        self.assertEqual(normalize_whitespace("alpha\u00a0beta\u2003gamma"), "alpha beta gamma")
    def test_line_breaks(self):
        self.assertEqual(normalize_whitespace("a\n\tb\rc"), "a b c")
    def test_single_word(self):
        self.assertEqual(normalize_whitespace("xyz"), "xyz")
