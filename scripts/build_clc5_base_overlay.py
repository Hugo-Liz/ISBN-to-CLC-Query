"""把官网第五版节点转换为项目可加载的基础类目覆盖层。"""

import argparse
import hashlib
import json
import re
from collections import defaultdict
from importlib import resources
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "clc_rules" / "clc5_base_overlay.json"
QUALIFIED_CODE = re.compile(r"^[A-Z]")
TRAILING_MARKERS = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩+|￠\s]+$")
# S50 是已由第五版纸本规则核对的仿分锚点，不作为单一图书分类号入库。
REVIEWED_NONASSIGNABLE_CODES = {"S50"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 对象存在重复键：{key}")
        result[key] = value
    return result


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=unique_object)


def read_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line, object_pairs_hook=unique_object)
            except json.JSONDecodeError as error:
                raise ValueError(f"节点文件第 {line_number} 行不是有效 JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"节点文件第 {line_number} 行不是对象")
            rows.append(row)
    return rows


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dependency_records(path=None):
    if path:
        return read_json(path)
    package = resources.files("chinese_library_classification")
    with package.joinpath("data", "data.json").open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=unique_object)


def clean_node(node):
    code = node["code"]
    label = node["label"].strip()
    name = node["name"].strip()
    notation = "ordinary"
    key = code
    marker = ""
    if label.startswith(f"[{code}]"):
        notation, key, marker = "bracketed", f"[{code}]", f"[{code}]"
    elif label.startswith(f"{{{code}}}"):
        notation, marker = "braced", f"{{{code}}}"
    if marker and name.startswith(marker):
        name = name[len(marker):].lstrip()
    name = TRAILING_MARKERS.sub("", name)
    if not name:
        raise ValueError(f"官网节点 {node['source_node_id']} 的类名为空")
    path_codes = node.get("path_codes")
    if not isinstance(path_codes, list) or not path_codes or path_codes[-1] != code:
        raise ValueError(f"官网节点 {node['source_node_id']} 的 path_codes 与分类号不一致")
    return {
        "raw_code": code,
        "key": key,
        "name": name,
        "notation": notation,
        "source_node_id": node["source_node_id"],
        "parent_raw_code": path_codes[-2] if len(path_codes) > 1 else None,
    }


def canonical_main_nodes(nodes):
    groups = defaultdict(list)
    for node in nodes:
        code = node.get("code")
        if node.get("table") != "main_table" or not isinstance(code, str) or not QUALIFIED_CODE.match(code):
            continue
        for field in ("label", "name", "source_node_id", "path_codes"):
            if field not in node:
                raise ValueError(f"官网主表节点缺少字段：{field}")
        groups[code].append(node)

    selected, skipped_range_codes, skipped_nonassignable_codes = [], [], []
    for code in sorted(groups):
        # A1/49、K21/27 这类节点描述范围/仿分规定，不是 A1、K21 的类名。
        concrete = [node for node in groups[code] if not node["label"].strip().startswith(code + "/")]
        if not concrete:
            skipped_range_codes.append(code)
            continue
        if len(concrete) != 1:
            labels = "；".join(node["label"] for node in concrete)
            raise ValueError(f"分类号 {code} 无法唯一确定实体节点：{labels}")
        cleaned = clean_node(concrete[0])
        if cleaned["key"] in REVIEWED_NONASSIGNABLE_CODES:
            skipped_nonassignable_codes.append(cleaned["key"])
            continue
        selected.append(cleaned)
    return selected, skipped_range_codes, skipped_nonassignable_codes


def validate_source(tree, nodes, allow_incomplete=False):
    if tree.get("schema_version") != "1.0":
        raise ValueError("暂不支持此官网树文件 schema_version")
    statistics = tree.get("statistics", {})
    if statistics.get("node_count") != len(nodes):
        raise ValueError("树文件统计的节点数与 JSONL 不一致")
    source_ids = [node.get("source_node_id") for node in nodes]
    if None in source_ids or len(source_ids) != len(set(source_ids)):
        raise ValueError("节点 source_node_id 缺失或重复")
    source_id_set = set(source_ids)
    orphans = [node["source_node_id"] for node in nodes
               if node.get("parent_source_node_id") is not None
               and node.get("parent_source_node_id") not in source_id_set]
    if orphans:
        raise ValueError("节点文件存在孤立父节点")
    validation = tree.get("validation", {})
    if validation.get("failed_requests"):
        raise ValueError("官网抓取记录中仍有失败请求")
    if tree.get("complete") is not True and not allow_incomplete:
        raise ValueError("官网树文件标记为不完整；复核后使用 --allow-incomplete 仅导入可确认节点")


def resolve_parent(parent_raw_code, raw_to_key, old_records):
    if parent_raw_code is None:
        return None
    if parent_raw_code in raw_to_key:
        return raw_to_key[parent_raw_code]
    if parent_raw_code in old_records:
        return parent_raw_code
    bracketed = f"[{parent_raw_code}]"
    if bracketed in old_records:
        return bracketed
    raise ValueError(f"官网父节点 {parent_raw_code} 在覆盖层和原依赖中均不存在")


def build_overlay(tree_path, nodes_path, dependency_path=None, allow_incomplete=False):
    tree = read_json(tree_path)
    nodes = read_jsonl(nodes_path)
    validate_source(tree, nodes, allow_incomplete=allow_incomplete)
    old_records = dependency_records(dependency_path)
    selected, skipped_range_codes, skipped_nonassignable_codes = canonical_main_nodes(nodes)
    raw_to_key = {row["raw_code"]: row["key"] for row in selected}
    if len(raw_to_key) != len(selected) or len({row["key"] for row in selected}) != len(selected):
        raise ValueError("官网实体节点映射后出现重复分类号")

    records = {}
    for row in selected:
        records[row["key"]] = {
            "name": row["name"],
            "up_level": resolve_parent(row["parent_raw_code"], raw_to_key, old_records),
            "notation": row["notation"],
            "source_node_id": row["source_node_id"],
        }
    superseded_dependency_codes = sorted(
        row["raw_code"] for row in selected
        if row["notation"] == "bracketed"
        and row["raw_code"] in old_records
        and row["key"] not in old_records
    )
    missing_parents = sorted({row["up_level"] for row in records.values()
                              if row["up_level"] is not None
                              and row["up_level"] not in records
                              and row["up_level"] not in old_records})
    if missing_parents:
        raise ValueError(f"覆盖数据仍有缺失父节点：{missing_parents[:5]}")

    added = sum(code not in old_records for code in records)
    changed_names = sum(code in old_records and old_records[code].get("name") != row["name"]
                        for code, row in records.items())
    changed_parents = sum(code in old_records and old_records[code].get("up_level") != row["up_level"]
                          for code, row in records.items())
    validation = tree.get("validation", {})
    return {
        "schema_version": "1.0",
        "edition": 5,
        "source": {
            "title": tree.get("title", "《中国图书馆分类法》（第五版）树状结构"),
            "url": tree.get("source_url"),
            "generated_at": tree.get("generated_at"),
            "complete": tree.get("complete") is True,
            "tree_sha256": sha256(tree_path),
            "nodes_sha256": sha256(nodes_path),
        },
        "import_policy": {
            "scope": "main_table_qualified_codes",
            "incomplete_source_mode": "verified_visible_nodes_only",
            "range_nodes": "excluded",
            "local_auxiliary_codes": "excluded",
            "bracketed_codes": "preserved_with_brackets",
            "parent_links": "official_path_codes",
            "reviewed_nonassignable_codes": "excluded",
        },
        "reviewed_nonassignable_codes": skipped_nonassignable_codes,
        "superseded_dependency_codes": superseded_dependency_codes,
        "statistics": {
            "source_nodes": len(nodes),
            "source_main_table_nodes": sum(node.get("table") == "main_table" for node in nodes),
            "source_common_auxiliary_nodes": sum(node.get("table") == "common_auxiliary_tables" for node in nodes),
            "source_max_depth": tree.get("statistics", {}).get("max_depth"),
            "source_depth_requirement_met": validation.get("depth_requirement_met"),
            "overlay_records": len(records),
            "dependency_records": len(old_records),
            "added_records": added,
            "changed_names": changed_names,
            "changed_parents": changed_parents,
            "superseded_dependency_records": len(superseded_dependency_codes),
            "skipped_range_only_codes": len(skipped_range_codes),
            "skipped_reviewed_nonassignable_codes": len(skipped_nonassignable_codes),
        },
        "records": records,
    }


def serialize(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", required=True, help="官网树文件 clc5_tree.json")
    parser.add_argument("--nodes", required=True, help="官网扁平节点文件 clc5_nodes.jsonl")
    parser.add_argument("--dependency-json", help="可选：指定原依赖 data.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="覆盖数据输出路径")
    parser.add_argument("--allow-incomplete", action="store_true",
                        help="允许导入标记为不完整的抓取结果；只保留可唯一确认的主表节点")
    parser.add_argument("--check", action="store_true", help="只检查现有输出是否可由输入重复生成")
    args = parser.parse_args(argv)
    data = build_overlay(args.tree, args.nodes, args.dependency_json, args.allow_incomplete)
    rendered = serialize(data)
    output = Path(args.output)
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != rendered:
            raise SystemExit("第五版基础覆盖数据需要重新生成")
        print(f"第五版基础覆盖数据一致：{data['statistics']['overlay_records']} 条")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    stats = data["statistics"]
    print(f"已生成 {output}：{stats['overlay_records']} 条，新增 {stats['added_records']} 条，"
          f"更新名称 {stats['changed_names']} 条，更新父链 {stats['changed_parents']} 条")


if __name__ == "__main__":
    main()
