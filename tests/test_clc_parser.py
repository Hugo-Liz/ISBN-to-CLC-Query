import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from unittest.mock import patch

from clc_parser import parse_clc
from clc_rules.base import BaseIndex, get_base, load_overlay
from clc_rules.engine import RuleParser, compact, get_registry


class BaseCompatibilityTest(unittest.TestCase):
    def test_dependency_fallback_and_official_overlay_are_merged(self):
        base = get_base()
        package = resources.files("chinese_library_classification")
        with package.joinpath("data", "data.json").open(encoding="utf-8") as stream:
            original = json.load(stream)
        overlay = load_overlay()
        superseded = set(overlay["superseded_dependency_codes"])
        expected_count = len(original) - len(superseded) + overlay["statistics"]["added_records"]
        self.assertEqual(len(base.records), expected_count)
        for code in original.keys() - base.official_codes - superseded:
            self.assertEqual(base.records[code]["name"], original[code]["name"], code)
            self.assertEqual(base.records[code]["up_level"], original[code]["up_level"], code)
        for code, official in overlay["records"].items():
            self.assertEqual(base.records[code]["name"], official["name"], code)
            self.assertEqual(base.records[code]["up_level"], official["up_level"], code)
        self.assertTrue(superseded.isdisjoint(base.records))

    def test_every_merged_parent_chain_and_child_link_is_valid(self):
        base = get_base()
        for code, row in base.records.items():
            with self.subTest(code=code):
                path = base.path(code)
                self.assertEqual(path[-1]["name"], row["name"])
                self.assertEqual(len(path), row["level"])
                if row["up_level"] is not None:
                    self.assertIn(code, base.records[row["up_level"]]["next_level"])

    def test_exact_matches_keep_original_names_and_paths(self):
        base = get_base()
        for code in ["TP311", "I247.5", "K825.72", "B313", "S512.1", "I3/7", "K833/837", "[K813]"]:
            with self.subTest(code=code):
                result = parse_clc(code)
                self.assertEqual(result["status"], "exact")
                self.assertEqual(result["path"], [node["name"] for node in base.path(code)])

    def test_all_named_original_codes_keep_paths_through_new_parser(self):
        base = get_base()
        parser = RuleParser(base)
        named, unnamed = 0, 0
        for code, row in base.records.items():
            if not row["name"]:
                unnamed += 1
                continue
            result = parser.parse(code, code)
            self.assertEqual(result["path"], [node["name"] for node in base.path(code)], code)
            self.assertTrue(result["complete"], code)
            named += 1
        self.assertEqual(named + unnamed, len(base.records))
        self.assertEqual(unnamed, 28)

    def test_fifth_edition_visible_nodes_override_stale_dependency_data(self):
        result = parse_clc("K237.1")
        self.assertIn("古代史中期（公元前475~公元581年）", result["path"])
        self.assertNotIn("封建社会（公元前475~公元1840年）", result["path"])
        self.assertTrue(any(source.get("kind") == "official_base_overlay" for source in result["sources"]))
        self.assertFalse(get_base().contains("G07"))
        self.assertTrue(get_base().contains("[G07]"))
        self.assertFalse(get_base().contains("S50"))

    def test_dependency_loaded_once_and_results_not_shared(self):
        base = get_base()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(parse_clc, ["I524.45"] * 16))
        results[0]["path"].append("不能污染其他结果")
        self.assertNotIn("不能污染其他结果", results[1]["path"])
        self.assertIs(base, get_base())

    def test_base_cycle_is_reported(self):
        base = BaseIndex({"I": {"name": "文学", "up_level": "I"}})
        with self.assertRaises(ValueError):
            base.path("I")

    def test_bad_supplement_does_not_remove_original_library(self):
        with patch("clc_rules.engine.get_registry", side_effect=ValueError("模拟规则数据损坏")):
            with self.assertLogs("clc_rules.engine", level="ERROR"):
                result = parse_clc("TP311")
        self.assertEqual(result["status"], "exact")
        self.assertTrue(result["path"])
        self.assertIn("补充规则暂不可用", result["warnings"][0])


class SubdivisionTest(unittest.TestCase):
    def test_every_registered_example(self):
        _tables, rules, _registry = get_registry()
        for rule in rules.values():
            for case in rule["cases"]:
                with self.subTest(rule=rule["id"], code=case["code"]):
                    result = parse_clc(case["code"])
                    self.assertNotEqual(result["status"], "unavailable")
                    for key in ("status", "code_status", "unparsed"):
                        if key in case:
                            self.assertEqual(result[key], case[key])
                    if "contains" in case:
                        self.assertIn(case["contains"], result["path_str"])
                        self.assertTrue(result["complete"])
                    if "not_contains" in case:
                        self.assertNotIn(case["not_contains"], result["path_str"])

    def test_foreign_literature_path(self):
        result = parse_clc("I524.45")
        self.assertEqual(result["path"], ["文学", "各国文学", "捷克文学", "小说", "现代小说"])
        self.assertEqual(result["status"], "supplemented")
        self.assertEqual(result["base_code"], "I3/7")
        self.assertIn("C5-I-COUNTRY", result["rule_ids"])

    def test_country_variants_and_aggregate_zero(self):
        for code, expected in [("I565.45", "法国文学"), ("I712.44", "美国文学"),
                               ("I312.645", "韩国文学"), ("I50.45", "欧洲文学")]:
            with self.subTest(code=code):
                result = parse_clc(code)
                self.assertIn(expected, result["path"])
                self.assertTrue(result["complete"])
        result = parse_clc("I59.45")
        self.assertEqual(result["status"], "partial")
        self.assertNotIn("现代小说", result["path"])

    def test_country_imitation_does_not_transfer_chinese_parent(self):
        result = parse_clc("K835.635.72=43")
        self.assertIn("荷兰人物传记", result["path"])
        self.assertIn("美术", result["path"])
        self.assertNotIn("中国人物传记", result["path"])
        self.assertIn("1870—1917", result["name"])
        self.assertEqual(result["unparsed"], "")

    def test_no_era_is_invented(self):
        result = parse_clc("K835.635.72")
        self.assertEqual(result["name"], "美术")
        self.assertFalse(any("TIME" in rule for rule in result["rule_ids"]))

    def test_table_parents_are_not_guessed_by_decimal_prefix(self):
        religion = parse_clc("I524.99")
        self.assertEqual(religion["name"], "宗教文学")
        self.assertNotIn("少数民族文学", religion["path"])
        report = parse_clc("I524.859")
        self.assertEqual(report["name"], "儿童报告文学")
        self.assertNotIn("儿童故事", report["path"])

    def test_chinese_and_international_time_context(self):
        self.assertIn("五代", parse_clc("K825.72=43")["name"])
        self.assertIn("1870—1917", parse_clc("K835.635.72=43")["name"])
        self.assertIn("民国", parse_clc("G254.12(2)=6")["name"])
        self.assertIn("21世纪", parse_clc("G254.12(711)=6")["name"])

    def test_same_table_number_is_not_same_meaning(self):
        self.assertIn("以色列", parse_clc("O4(382)")["path_str"])
        self.assertIn("犹太人", parse_clc('O4"382"')["path_str"])
        self.assertNotIn("以色列", parse_clc('O4"382"')["path_str"])

    def test_discontinued_numbers_preserve_original_and_old_meaning(self):
        for code in ["O4-08", "K835.635.72=44", "K825.72=31"]:
            with self.subTest(code=code):
                result = parse_clc(code)
                self.assertEqual(result["code"], code)
                self.assertEqual(result["code_status"], "discontinued")
                self.assertTrue(result["complete"])
                self.assertTrue(any("停用" in warning for warning in result["warnings"]))

    def test_historical_region_is_not_automatically_discontinued(self):
        result = parse_clc("O4(223)")
        self.assertTrue(result["complete"])
        self.assertEqual(result["code_status"], "historical")
        self.assertIn("热河省", result["path_str"])

    def test_ancient_regions_explain_meaning_without_certifying_usage(self):
        for code, place in [("I12(198.4)", "古代希腊"), ("I12(198.5)", "古代罗马"),
                            ("O4(198.5)", "古代罗马"), ("S3-091.985", "古代罗马"),
                            ("I109.2(198.4)", "古代希腊")]:
            with self.subTest(code=code):
                result = parse_clc(code)
                self.assertEqual(result["code"], code)
                self.assertEqual(result["status"], "supplemented")
                self.assertEqual(result["code_status"], "historical")
                self.assertEqual(result["unparsed"], "")
                self.assertTrue(result["complete"])
                self.assertIn(place, result["path"])
                self.assertTrue(any("历史属性" in warning and "未鉴定" in warning
                                    for warning in result["warnings"]))
                self.assertIn("C5-WORLD-REGION", result["rule_ids"])
        result = parse_clc("I12(198.4)")
        self.assertEqual(result["path"], ["文学", "世界文学", "作品集", "诗歌集", "古代希腊"])
        self.assertEqual(result["path_nodes"][-1]["table_code"], "1984")

    def test_unknown_or_incomplete_ancient_region_is_not_partly_committed(self):
        for tail in ["(198.6)", "(198.4.1)", "(198.4", "(198.4ABC)", "(999)"]:
            with self.subTest(tail=tail):
                result = parse_clc("I12" + tail)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["unparsed"], tail)
                self.assertEqual(result["path"], parse_clc("I12")["path"])
                self.assertEqual(result["code_status"], "not_assessed")
                self.assertNotIn("C5-WORLD-REGION", result["rule_ids"])

    def test_ancient_region_warning_does_not_hide_other_statuses_or_unknown_tail(self):
        result = parse_clc("O4-08(198.4)")
        self.assertEqual(result["code_status"], "discontinued")
        self.assertIn("古代希腊", result["path"])
        self.assertTrue(any("历史属性" in warning for warning in result["warnings"]))
        result = parse_clc("I12(198.4)=999")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["unparsed"], "=999")
        self.assertEqual(result["matched_code"], "I12(198.4)")
        self.assertEqual(result["code_status"], "historical")

    def test_unreviewed_ancient_region_rule_is_not_executed(self):
        registry = copy.deepcopy(get_registry())
        registry[1]["C5-WORLD-REGION"]["review_status"] = "pending"
        result = RuleParser(registry=registry).parse("I12(198.4)", "I12(198.4)")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["unparsed"], "(198.4)")
        self.assertEqual(result["code_status"], "not_assessed")

    def test_ancient_region_does_not_change_other_region_or_time_results(self):
        parse_clc("I12(198.4)")
        modern = parse_clc("I12(545)")
        self.assertEqual(modern["name"], "希腊")
        self.assertEqual(modern["code_status"], "not_assessed")
        self.assertEqual(modern["warnings"], [])
        biography = parse_clc("K837.125.6=6")
        self.assertIn("美国人物传记", biography["path"])
        self.assertIn("21世纪", biography["name"])
        self.assertEqual(biography["code_status"], "not_assessed")

    def test_dedicated_foreign_literature_categories_win(self):
        result = parse_clc("I524-29")
        self.assertEqual(result["name"], "文学市场")
        self.assertNotIn("生产单位", result["path_str"])

    def test_normalization_preserves_raw_input(self):
        original = "  ｋ８３５．６３５．７２＝４３ \n"
        result = parse_clc(original)
        self.assertEqual(result["code"], original)
        self.assertEqual(result["normalized_code"], "K835.635.72=43")
        self.assertEqual(result["status"], "supplemented")
        self.assertIn("苗族", parse_clc('TS959.2“216”')["path"])

    def test_truncation_is_explicit_partial(self):
        result = parse_clc("TP311.12")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["base_code"], "TP311.1")
        self.assertEqual(result["unparsed"], "2")
        self.assertFalse(result["complete"])

    def test_unsupported_tail_is_not_discarded(self):
        for code in ["I524.45:K", "I524.45;K825.72", "I524.45=999", "I524.45(999)",
                     "I524.45(563", "I524.45[=43]", "I524.45<999>", "I524.45-61-62"]:
            with self.subTest(code=code):
                result = parse_clc(code)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["matched_code"] + result["unparsed"], result["normalized_code"])
                self.assertFalse(result["complete"])

    def test_no_later_marker_is_parsed_after_unknown_part(self):
        result = parse_clc("I524.4999=43")
        self.assertNotIn("1870—1917", result["path_str"])
        self.assertEqual(result["status"], "partial")

    def test_unreviewed_rule_is_not_executed(self):
        registry = copy.deepcopy(get_registry())
        registry[1]["C5-I-COUNTRY"]["review_status"] = "pending"
        result = RuleParser(registry=registry).parse("I524.45", "I524.45")
        self.assertEqual(result["path"], ["文学"])
        self.assertEqual(result["status"], "partial")

    def test_unreviewed_chained_rule_is_not_executed(self):
        registry = copy.deepcopy(get_registry())
        registry[1]["C5-WORLD-ETHNIC"]["review_status"] = "pending"
        result = RuleParser(registry=registry).parse("K837.128.738.2", "K837.128.738.2")
        self.assertEqual(result["status"], "partial")
        self.assertNotIn("犹太人", result["path"])

    def test_explicit_symbol_class_is_retained_before_further_subdivision(self):
        result = parse_clc("Q98-08=43")
        self.assertIn("资产阶级人类学及其研究", result["path"])
        self.assertEqual(result["code_status"], "discontinued")
        result = parse_clc("S512.1+1(711)")
        self.assertIn("冬小麦", result["path"])
        self.assertIn("加拿大", result["path"])

    def test_generic_imitation_preserves_source_parent(self):
        records = {
            "I": {"name": "文学", "up_level": None},
            "I266": {"name": "现代散文", "up_level": "I"},
            "I266.1": {"name": "杂文", "up_level": "I266"},
            "I267": {"name": "当代散文", "up_level": "I"},
        }
        result = RuleParser(base=BaseIndex(records)).parse("I267.1", "I267.1")
        self.assertEqual(result["path"], ["文学", "当代散文", "杂文"])

    def test_empty_invalid_unknown_and_unavailable(self):
        self.assertEqual(parse_clc(None)["status"], "empty")
        self.assertEqual(parse_clc("   ")["status"], "empty")
        self.assertEqual(parse_clc("12345")["status"], "invalid")
        self.assertEqual(parse_clc("I5..24")["status"], "invalid")
        self.assertEqual(parse_clc("W999")["status"], "unknown")
        with patch("clc_rules.engine.get_base", side_effect=OSError("模拟读取失败")):
            with self.assertLogs("clc_rules.engine", level="ERROR"):
                result = parse_clc("I524.45")
        self.assertEqual(result["status"], "unavailable")

    def test_provenance_and_json_serialization(self):
        result = parse_clc("K835.635.72=43")
        source = next(item for item in result["sources"] if item.get("rule_id") == "C5-K-COUNTRY-BIOGRAPHY")
        self.assertIn(251, source["pdf_pages"])
        self.assertIn(1023, next(item for item in result["sources"] if item.get("table_id") == "international_time")["pdf_pages"])
        self.assertEqual(json.loads(json.dumps(result))["path"], result["path"])


if __name__ == "__main__":
    unittest.main()
