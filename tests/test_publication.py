import json
import unittest

from scripts.check_publication import scan_file, scan_text
from scripts.index_clc_rules import build_index


class PublicationSafetyTest(unittest.TestCase):
    def test_private_paths_tokens_and_credentials_are_detected_without_values(self):
        samples = ["/" + "Users/fictional/project", "gh" + "p_" + "a" * 30,
                   "https://" + "example:private-value@proxy.example.invalid",
                   "test-person@" + "private.invalid"]
        for sample in samples:
            with self.subTest():
                findings = scan_text(sample)
                self.assertTrue(findings)
                self.assertNotIn(sample, str(findings))

    def test_runtime_and_private_files_are_rejected(self):
        for path in ("private/index.json", "data/cache.sqlite3", ".env.local", "book.pdf", "queries.xlsx"):
            with self.subTest(path=path):
                self.assertTrue(scan_file(path, b""))

    def test_public_examples_and_privacy_email_are_allowed(self):
        self.assertEqual(scan_text("https://example.invalid\n123+example@users.noreply.github.com"), [])
        self.assertEqual(scan_file("README.md", "公开说明".encode()), [])

    def test_index_private_fields_are_blocked(self):
        index = build_index("依世界地区表分。\f", include_private=True)
        self.assertTrue(scan_file("clc_rules/inventory.json", json.dumps(index).encode()))
        public = build_index("依世界地区表分。\f")
        self.assertEqual(scan_file("clc_rules/inventory.json", json.dumps(public).encode()), [])
