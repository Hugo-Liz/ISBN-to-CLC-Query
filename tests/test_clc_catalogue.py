import json
import unittest

from clc_rules.engine import get_registry, unique_keys
from scripts.build_clc_catalogue import ROOT, build_catalogue
from scripts.index_clc_rules import build_index, public_index


class ClassificationCatalogueTest(unittest.TestCase):
    def test_generated_document_matches_current_data(self):
        expected = (ROOT / "docs" / "clc-rule-coverage.md").read_text(encoding="utf-8")
        self.assertEqual(build_catalogue(), expected)

    def test_candidate_scan_does_not_enable_rules(self):
        index = build_index("例：依世界地区表分，再仿K82分。\f空白页\f")
        self.assertEqual(index["page_count"], 2)
        self.assertEqual(index["candidate_count"], 1)
        candidate = index["candidates"][0]
        self.assertEqual(candidate["review_status"], "pending")
        self.assertEqual(candidate["rule_ids"], [])
        self.assertIn("依表", candidate["kinds"])
        self.assertIn("仿分", candidate["kinds"])

    def test_source_table_entries_are_unique_and_rules_have_evidence(self):
        tables, rules, _registry = get_registry()
        self.assertGreaterEqual(len(tables), 8)
        for rule in rules.values():
            self.assertTrue(rule["scope"])
            self.assertTrue(rule["pdf_pages"])
            self.assertGreaterEqual(len(rule["cases"]), 2)
        with self.assertRaises(ValueError):
            json.loads('{"43":"近代","43":"五代"}', object_pairs_hook=unique_keys)

    def test_public_index_removes_private_metadata_and_ocr(self):
        private = build_index("私有定位文字：依世界地区表分。\f", "a" * 64, include_private=True)
        private["source"] = "私有来源信息"
        private["future_private_field"] = "不应发布"
        private["candidates"][0]["future_private_field"] = "不应发布"
        result = public_index(private)
        serialized = json.dumps(result, ensure_ascii=False)
        for value in ("私有定位文字", "私有来源信息", "不应发布", "locator_hint", "pdf_sha256", "text_sha256"):
            self.assertNotIn(value, serialized)
        self.assertEqual(result["candidate_count"], private["candidate_count"])
        self.assertEqual(result["candidates"][0]["id"], private["candidates"][0]["id"])
        self.assertIn("locator_hint", private["candidates"][0])

    def test_default_and_committed_indexes_are_public(self):
        for index in (build_index("依世界地区表分。\f"),
                      json.loads((ROOT / "clc_rules" / "inventory.json").read_text(encoding="utf-8"))):
            self.assertEqual(index, public_index(index))


if __name__ == "__main__":
    unittest.main()
