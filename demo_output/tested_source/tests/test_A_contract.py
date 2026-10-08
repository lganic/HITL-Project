import unittest
from solution import normalize_whitespace

class ContractTests(unittest.TestCase):
    def test_words(self):
        self.assertEqual(normalize_whitespace("  hello   world  "), "hello world")
    def test_empty(self):
        self.assertEqual(normalize_whitespace(""), "")
        self.assertEqual(normalize_whitespace(" \n\t"), "")
    def test_bad_input(self):
        for value in [None, 42, [], b"hello"]:
            with self.assertRaises(TypeError):
                normalize_whitespace(value)
