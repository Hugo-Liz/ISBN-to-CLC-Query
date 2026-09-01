import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_clc5_base_overlay import build_overlay, clean_node


class OfficialBaseOverlayBuilderTest(unittest.TestCase):
    def test_incomplete_source_requires_explicit_mode_and_keeps_only_qualified_main_codes(self):
        nodes = [
            self.node("root", None, "主表", None, [], "main_table"),
            self.node("k", "K", "历史、地理", "root", ["K"], "main_table"),
            self.node("k2", "K2", "中国史", "k", ["K", "K2"], "main_table"),
            self.node("range", "K21", "/27 中国各代史", "k2", ["K", "K2", "K21"],
                      "main_table", label="K21/27 中国各代史"),
            self.node("k21", "K21", "上古史⑨", "k2", ["K", "K2", "K21"], "main_table"),
            self.node("aux", None, "通用复分表", None, [], "common_auxiliary_tables"),
            self.node("aux1", "1", "世界", "aux", ["1"], "common_auxiliary_tables"),
        ]
        tree = {
            "schema_version": "1.0", "title": "第五版测试树", "source_url": "https://example.invalid/clc5",
            "generated_at": "2026-08-31T00:00:00+08:00", "complete": False,
            "statistics": {"node_count": len(nodes), "max_depth": 3},
            "validation": {"failed_requests": [], "depth_requirement_met": False},
        }
        dependency = {
            "K": self.record("历史地理（旧）", None),
            "K2": self.record("中国史（旧）", "K"),
            "K21": self.record("旧上古史", "K2"),
        }
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            tree_path, nodes_path, dependency_path = folder / "tree.json", folder / "nodes.jsonl", folder / "data.json"
            tree_path.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
            nodes_path.write_text("\n".join(json.dumps(node, ensure_ascii=False) for node in nodes) + "\n",
                                  encoding="utf-8")
            dependency_path.write_text(json.dumps(dependency, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "--allow-incomplete"):
                build_overlay(tree_path, nodes_path, dependency_path)
            overlay = build_overlay(tree_path, nodes_path, dependency_path, allow_incomplete=True)
        self.assertEqual(set(overlay["records"]), {"K", "K2", "K21"})
        self.assertEqual(overlay["records"]["K21"]["name"], "上古史")
        self.assertEqual(overlay["records"]["K21"]["up_level"], "K2")
        self.assertEqual(overlay["statistics"]["source_common_auxiliary_nodes"], 2)
        self.assertFalse(overlay["source"]["complete"])

    def test_bracket_notation_remains_part_of_the_effective_code(self):
        node = self.node("c7", "C7", "[C7] 社会科学文献检索工具书⑨", "c", ["C", "C7"],
                         "main_table", label="[C7] 社会科学文献检索工具书⑨")
        cleaned = clean_node(node)
        self.assertEqual(cleaned["key"], "[C7]")
        self.assertEqual(cleaned["name"], "社会科学文献检索工具书")
        self.assertEqual(cleaned["notation"], "bracketed")

    @staticmethod
    def node(source_id, code, name, parent_id, path_codes, table, label=None):
        return {
            "source_node_id": source_id,
            "parent_source_node_id": parent_id,
            "code": code,
            "name": name,
            "label": label if label is not None else (name if code is None else f"{code} {name}"),
            "path_codes": path_codes,
            "table": table,
        }

    @staticmethod
    def record(name, parent):
        return {"name": name, "level": 1, "link1": "", "link2": "", "up_level": parent,
                "next_level": []}


if __name__ == "__main__":
    unittest.main()
