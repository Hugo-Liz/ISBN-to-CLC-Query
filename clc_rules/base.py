"""合并原依赖与官网第五版覆盖数据，并一次性建立基础类目索引。"""

import json
import re
from functools import lru_cache
from importlib import metadata, resources
from pathlib import Path


OVERLAY_PATH = Path(__file__).with_name("clc5_base_overlay.json")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"基础分类数据存在重复键：{key}")
        result[key] = value
    return result


class BaseIndex:
    def __init__(self, records, version="0.0.1", official_records=None, official_source=None):
        self.records = records
        self.version = version
        self.official_records = official_records or {}
        self.official_codes = frozenset(self.official_records)
        self.official_source = official_source

    def contains(self, code):
        return bool(self.records.get(code, {}).get("name"))

    def path(self, code):
        nodes, seen = [], set()
        while code is not None:
            if code in seen:
                raise ValueError("基础分类父链存在循环")
            seen.add(code)
            row = self.records[code]
            source = "official_clc5" if code in self.official_codes else "dependency"
            nodes.append({"code": code, "name": row["name"], "source": source})
            code = row["up_level"]
        return list(reversed(nodes))

    def longest_prefix(self, code):
        for length in range(len(code), 0, -1):
            candidate = code[:length]
            if not candidate.endswith(".") and self.contains(candidate):
                return candidate
        return ""


def validate_dependency(records):
    if not isinstance(records, dict) or not all(
        isinstance(code, str) and isinstance(row, dict)
        and "name" in row and "up_level" in row
        for code, row in records.items()
    ):
        raise ValueError("原分类依赖的数据结构已变化，请检查适配层")


def load_overlay():
    with OVERLAY_PATH.open(encoding="utf-8") as stream:
        overlay = json.load(stream, object_pairs_hook=unique_object)
    if overlay.get("schema_version") != "1.0" or overlay.get("edition") != 5:
        raise ValueError("第五版基础覆盖数据版本不受支持")
    source = overlay.get("source")
    records = overlay.get("records")
    stats = overlay.get("statistics")
    superseded = overlay.get("superseded_dependency_codes")
    nonassignable = overlay.get("reviewed_nonassignable_codes")
    if not isinstance(source, dict) or not isinstance(records, dict) or not isinstance(stats, dict):
        raise ValueError("第五版基础覆盖数据缺少来源、统计或类目")
    if not isinstance(superseded, list) or len(superseded) != len(set(superseded)):
        raise ValueError("第五版基础覆盖数据的替代类目列表无效")
    if (not isinstance(nonassignable, list) or len(nonassignable) != len(set(nonassignable))
            or any(code in records for code in nonassignable)):
        raise ValueError("第五版基础覆盖数据的非入库类目列表无效")
    if stats.get("overlay_records") != len(records):
        raise ValueError("第五版基础覆盖数据的类目数量校验失败")
    if stats.get("superseded_dependency_records") != len(superseded):
        raise ValueError("第五版基础覆盖数据的替代类目数量校验失败")
    if stats.get("skipped_reviewed_nonassignable_codes") != len(nonassignable):
        raise ValueError("第五版基础覆盖数据的非入库类目数量校验失败")
    if not all(isinstance(source.get(field), str) and source[field]
               for field in ("title", "url", "generated_at", "tree_sha256", "nodes_sha256")):
        raise ValueError("第五版基础覆盖数据的来源字段不完整")
    if not all(SHA256.fullmatch(source[field]) for field in ("tree_sha256", "nodes_sha256")):
        raise ValueError("第五版基础覆盖数据的来源摘要无效")
    if not all(
        isinstance(code, str) and code
        and isinstance(row, dict)
        and isinstance(row.get("name"), str) and row["name"]
        and (row.get("up_level") is None or isinstance(row.get("up_level"), str))
        and row.get("notation") in {"ordinary", "bracketed", "braced"}
        and isinstance(row.get("source_node_id"), str) and row["source_node_id"]
        for code, row in records.items()
    ):
        raise ValueError("第五版基础覆盖类目的字段无效")
    return overlay


def rebuild_hierarchy(records):
    children = {code: [] for code in records}
    for code, row in records.items():
        parent = row["up_level"]
        if parent is not None:
            if parent not in records:
                raise ValueError(f"基础分类父节点不存在：{code} -> {parent}")
            children[parent].append(code)

    visiting, levels = set(), {}

    def level(code):
        if code in levels:
            return levels[code]
        if code in visiting:
            raise ValueError(f"基础分类父链存在循环：{code}")
        visiting.add(code)
        parent = records[code]["up_level"]
        value = 1 if parent is None else level(parent) + 1
        visiting.remove(code)
        levels[code] = value
        return value

    for code, row in records.items():
        row["level"] = level(code)
        row["next_level"] = children[code]


def merge_records(dependency, overlay):
    stats = overlay["statistics"]
    if stats.get("dependency_records") != len(dependency):
        raise ValueError("安装的原依赖数据数量与第五版覆盖层的生成基线不一致")
    records = {code: dict(row) for code, row in dependency.items()}
    for code in overlay["superseded_dependency_codes"]:
        if code not in records:
            raise ValueError(f"第五版声明替代的原类目不存在：{code}")
        del records[code]
    for code, official in overlay["records"].items():
        row = records.get(code, {
            "name": "", "level": 0, "link1": "", "link2": "",
            "up_level": None, "next_level": [],
        })
        row["name"] = official["name"]
        row["up_level"] = official["up_level"]
        records[code] = row
    expected = len(dependency) - len(overlay["superseded_dependency_codes"]) + stats["added_records"]
    if len(records) != expected:
        raise ValueError("第五版基础覆盖数据合并后的类目数量异常")
    rebuild_hierarchy(records)
    return records


@lru_cache(maxsize=1)
def get_base():
    package = resources.files("chinese_library_classification")
    with package.joinpath("data", "data.json").open(encoding="utf-8") as stream:
        dependency = json.load(stream, object_pairs_hook=unique_object)
    validate_dependency(dependency)
    overlay = load_overlay()
    records = merge_records(dependency, overlay)
    source = dict(overlay["source"])
    source.update({
        "kind": "official_base_overlay",
        "edition": overlay["edition"],
        "records": overlay["statistics"]["overlay_records"],
    })
    return BaseIndex(
        records,
        metadata.version("chinese-library-classification"),
        official_records=overlay["records"],
        official_source=source,
    )
