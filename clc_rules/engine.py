"""可追溯的离线复分解析器：原库精确匹配优先，规则只补充已核对部分。"""

import copy
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .base import get_base


LOGGER = logging.getLogger(__name__)
STATUS_LABELS = {
    "exact": "原库精确匹配", "supplemented": "规则补全", "partial": "部分解析",
    "unknown": "未识别", "empty": "无分类号", "invalid": "格式异常", "unavailable": "解析服务异常",
}
VALIDITY_LABELS = {
    "not_assessed": "未作编目有效性鉴定", "discontinued": "含第五版停用号",
    "alternative": "含交替类目", "historical": "含历史地区号",
    "nonpreferred": "主表另有专类", "reference_only": "类表范围或标记，非单一图书类号",
}


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"补充数据存在重复键：{key}")
        result[key] = value
    return result


@lru_cache(maxsize=1)
def get_registry():
    folder = Path(__file__).parent
    with (folder / "tables.json").open(encoding="utf-8") as stream:
        tables = json.load(stream, object_pairs_hook=unique_keys)["tables"]
    with (folder / "rules.json").open(encoding="utf-8") as stream:
        registry = json.load(stream, object_pairs_hook=unique_keys)
    rules = {rule["id"]: rule for rule in registry["rules"]}
    if len(rules) != len(registry["rules"]):
        raise ValueError("规则 ID 重复")
    for rule in rules.values():
        if not rule.get("pdf_pages") or not rule.get("cases"):
            raise ValueError(f"规则缺少来源或测试：{rule['id']}")
        if any(table not in tables for table in rule["table_ids"]):
            raise ValueError(f"规则引用未知表：{rule['id']}")
        operators = {"general", "marked_region", "china_region", "marked_time", "china_time",
                     "marked_ethnic", "china_ethnic", "environment", "foreign_literature",
                     "country_biography", "world_biography", "append_table", "imitate",
                     "zero_table_imitation", "annotation"}
        if rule["operator"] not in operators:
            raise ValueError(f"未知执行类型：{rule['id']}")
        if not all(isinstance(page, int) and 1 <= page <= 1041 for page in rule["pdf_pages"]):
            raise ValueError(f"规则页码不属于此版PDF：{rule['id']}")
    for table in tables.values():
        if not all(re.fullmatch(r"\d+", key) and isinstance(name, str) and name for key, name in table["entries"].items()):
            raise ValueError("补充表的表号或名称不符合约定")
        for key, parent in table.get("parents", {}).items():
            if key not in table["entries"] or parent not in table["entries"] or key == parent:
                raise ValueError("补充表父节点引用不合法")
    return tables, rules, registry


def compact(code):
    return code.replace(".", "")


def format_number(code):
    """仅用于重建已知主类的展示分组，不以小数点猜测语义层级。"""
    match = re.fullmatch(r"([A-Z]+)(\d*)", code)
    if not match:
        return code
    letters, digits = match.groups()
    return letters + ".".join(digits[i:i + 3] for i in range(0, len(digits), 3))


def raw_offset(raw, packed_length):
    """把去点后的已消费长度映射回规范串，未解析部分保留分隔点。"""
    count = 0
    for index, char in enumerate(raw):
        if char != ".":
            count += 1
        if count == packed_length:
            return index + 1
    return len(raw)


def longest_key(entries, value):
    return next((key for key in sorted(entries, key=len, reverse=True) if value.startswith(key)), "")


@dataclass
class Resolution:
    nodes: list
    base_code: str
    consumed: int
    country: str = "international"
    rules: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    code_status: str = "not_assessed"
    context: dict = field(default_factory=dict)

    def mark(self, rule_id):
        if rule_id not in self.rules:
            self.rules.append(rule_id)

    def node(self, name, code, rule_id, table_id=None, table_code=None):
        self.mark(rule_id)
        row = {"name": name, "code": code, "source": "rule", "rule_id": rule_id}
        if table_id:
            row.update(table_id=table_id, table_code=table_code)
            if table_id not in self.tables:
                self.tables.append(table_id)
        self.nodes.append(row)

    def flag(self, status, note):
        # 停用提示不能被后续正常或历史属性覆盖。
        rank = {"not_assessed": 0, "historical": 1, "alternative": 2, "nonpreferred": 3, "discontinued": 4}
        if rank.get(status, 0) > rank.get(self.code_status, 0):
            self.code_status = status
        if note not in self.warnings:
            self.warnings.append(note)


class RuleParser:
    def __init__(self, base=None, registry=None):
        self.base = base if base is not None else get_base()
        self.registry_warning = ""
        try:
            self.tables, self.rules, self.registry = registry or get_registry()
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            LOGGER.exception("补充规则不可用，保留原库解析")
            self.tables, self.rules = {}, {}
            self.registry = {"version": "unavailable", "exceptions": []}
            self.registry_warning = "补充规则暂不可用；这里只返回原库能确认的路径。"

    def enabled(self, rule_id):
        rule = self.rules.get(rule_id, {})
        return rule.get("review_status") == "reviewed" and rule.get("implementation_status") in {"implemented", "partial"}

    def from_base(self, code, consumed=None):
        nodes = self.base.path(code)
        # 国家属性只来自明确类名/已解析地区，绝不从书名或作者推断。
        country = "china" if any(node["name"].startswith("中国") for node in nodes) else "international"
        return Resolution(nodes, code, len(code) if consumed is None else consumed, country)

    def add_table(self, result, table_id, key, rule_id, code="", label=None):
        table = self.tables[table_id]
        name = table["entries"][key]
        result.node(label or name, code, rule_id, table_id, key)
        result.notes.append(f"{table['name']} {key}：{name}")
        for status in ("discontinued", "alternative"):
            if key in table.get(status, {}):
                result.flag(status, table[status][key])
        if key in table.get("historical", []):
            result.flag("historical", f"{name}是第五版保留的历史地区；不自动替换为现行名称。")

    def region_parts(self, value, foreign_only=False):
        """地区前缀；聚合地区再接标准时必须有0。"""
        entries = self.tables["world_region"]["entries"]
        key = longest_key(entries, value)
        if not key or (foreign_only and key[0] not in "34567"):
            return None
        end = len(key)
        if key in self.tables["world_region"].get("aggregate", []) and len(value) > end:
            if value[end] != "0":
                return key, end, False
            end += 1
        return key, end, True

    def add_china_region(self, result, value, rule_id, code=""):
        if not self.enabled("C5-CHINA-REGION"):
            return 0
        table = self.tables["china_region"]
        key = longest_key(table["entries"], value)
        if not key:
            return 0
        self.add_table(result, "china_region", key, rule_id, code)
        result.mark("C5-CHINA-REGION")
        result.country = "china"
        end = len(key)
        tail = value[end:]
        if key not in table["aggregate"] and tail and tail[0] in table["administrative"]:
            result.node(table["administrative"][tail[0]], code, rule_id, "china_region", tail[0])
            end += 1
            if re.fullmatch(r"[A-Z]{2}", tail[1:]):
                result.notes.append(f"地名助记字母 {tail[1:]}：仅保留原记号，不反推具体地名。")
                end += 2
        return end

    def add_world_region(self, result, value, rule_id, code=""):
        if not self.enabled(rule_id):
            return 0
        if value.startswith("2"):
            self.add_table(result, "world_region", "2", rule_id, code)
            result.country = "china"
            if len(value) > 1:
                return 1 + self.add_china_region(result, value[1:], "C5-CHINA-REGION", code)
            return 1
        part = self.region_parts(value)
        if not part:
            return 0
        key, _, _ = part
        self.add_table(result, "world_region", key, rule_id, code)
        # 地区号的已知含义与编目适用性分开；不能用类名关键词代替适用性审核。
        if key in self.tables["world_region"].get("historical_only", []):
            result.flag("historical", "世界地区表198.1/.8的古代地区号有历史属性适用限制；"
                        "这里仅解释原号中的地区含义，本书使用该复分号是否合规尚未鉴定。")
        result.country = "international"
        return len(key)

    def add_ethnic(self, result, value, rule_id, code=""):
        if not self.enabled(rule_id):
            return 0
        if value.startswith("2"):
            self.add_table(result, "world_ethnic", "2", rule_id, code)
            if len(value) == 1:
                return 1
            key = longest_key(self.tables["china_ethnic"]["entries"], value[1:]) if self.enabled("C5-CHINA-ETHNIC") else ""
            if key:
                self.add_table(result, "china_ethnic", key, "C5-CHINA-ETHNIC", code)
            return 1 + len(key)
        key = longest_key(self.tables["world_ethnic"]["entries"], value)
        if key:
            self.add_table(result, "world_ethnic", key, rule_id, code)
        return len(key)

    def literature(self, raw):
        rule_id = "C5-I-COUNTRY"
        packed = compact(raw)
        if not self.enabled(rule_id) or not re.match(r"I[3-7]", packed):
            return None
        part = self.region_parts(packed[1:], foreign_only=True)
        if not part:
            return None
        region, end, can_continue = part
        result = self.from_base("I3/7", 0)
        result.context["foreign_literature"] = True
        self.add_table(result, "world_region", region, rule_id,
                       format_number("I" + region), self.tables["world_region"]["entries"][region] + "文学")
        result.consumed = raw_offset(raw, 1 + len(region))
        if not can_continue:
            return result
        tail = packed[1 + end:]
        if not tail:
            return result
        table = self.tables["foreign_literature"]
        used = 0
        # 只有明确仿09的作品类型可接时代，民间文学、儿童文学不得套此规则。
        if len(tail) >= 2 and tail[0] in table["period_genres"] and tail[1] in table["periods"]:
            genre, era = tail[:2]
            genre_name = table["entries"][genre]
            self.add_table(result, "foreign_literature", genre, rule_id, label=genre_name)
            result.node(table["periods"][era] + genre_name, "", rule_id, "foreign_literature", genre + era)
            result.notes.append(f"I3/7专用表：{genre_name}仿09，以{era}表示{table['periods'][era]}；不套中国文学的年代。")
            used = 2
            if genre == "4" and len(tail) > 2 and self.enabled("C5-I-NOVEL-TOPIC"):
                topic = tail[2]
                if topic in self.tables["novel_topic"]["entries"]:
                    self.add_table(result, "novel_topic", topic, "C5-I-NOVEL-TOPIC")
                    used += 1
        else:
            key = longest_key(table["entries"], tail)
            if key:
                parent = table["parents"].get(key)
                if parent:
                    self.add_table(result, "foreign_literature", parent, rule_id)
                self.add_table(result, "foreign_literature", key, rule_id)
                used = len(key)
        if used:
            result.context["literature_genre"] = True
            result.consumed = raw_offset(raw, 1 + end + used)
        return result

    def biography(self, raw):
        packed = compact(raw)
        country_rule = "C5-K-COUNTRY-BIOGRAPHY"
        world_rule = "C5-K-WORLD-BIOGRAPHY"
        if packed.startswith("K83") and self.enabled(country_rule):
            part = self.region_parts(packed[3:], foreign_only=True)
            if not part:
                return None
            region, end, can_continue = part
            result = self.from_base("K833/837", 0)
            result.country = "international"
            rule_id = country_rule
            self.add_table(result, "world_region", region, rule_id, format_number("K83" + region),
                           self.tables["world_region"]["entries"][region] + "人物传记")
            result.consumed = raw_offset(raw, 3 + len(region))
            if not can_continue:
                return result
            start = 3 + end
            tail = packed[start:]
        elif re.match(r"K81[5-8]", packed) and self.enabled(world_rule):
            result = self.from_base("K815", 0)
            result.country = "international"
            rule_id = world_rule
            start, tail = 3, packed[3:]
            result.consumed = min(len(raw), 4)
        else:
            return None
        if not tail:
            return result
        # 仿K820按时代时用国际表；08外国国内地区不得仿中国地区表。
        if tail.startswith("0") and rule_id == country_rule:
            if tail.startswith("08"):
                result.node("人物总传：按地区", "", rule_id)
                used = 2
            elif tail.startswith("09"):
                result.node("氏族谱系", "", rule_id)
                used = 2
            else:
                result.node("人物总传：按时代", "", rule_id)
                key = longest_key(self.tables["international_time"]["entries"], tail[1:]) if self.enabled("C5-INTERNATIONAL-TIME") else ""
                if key:
                    self.add_table(result, "international_time", key, "C5-INTERNATIONAL-TIME")
                used = 1 + len(key)
            result.consumed = raw_offset(raw, start + used)
            return result
        if tail[0] not in "5678":
            return result
        target = "K82" + tail
        matched = ""
        for size in range(len(target), 3, -1):
            candidate = format_number(target[:size])
            if self.base.contains(candidate):
                matched = candidate
                break
        if not matched:
            return result
        # 只移植K82之后的相对路径，去掉“中国人物传记”及其祖先。
        target_path = self.base.path(matched)
        seen_anchor = False
        for node in target_path:
            if node["code"] == "K82":
                seen_anchor = True
                continue
            if seen_anchor and not (rule_id == world_rule and node["code"] == "K825"):
                result.node(node["name"], "", rule_id)
        result.mark(rule_id)
        result.notes.append(f"仿原库{matched}的相对细目；不移植中国父类、地区或时代上下文。")
        used = len(compact(matched)) - 3
        if compact(matched) == "K8287" and len(tail) > used and rule_id == country_rule:
            used += self.add_ethnic(result, tail[used:], "C5-WORLD-ETHNIC")
        result.consumed = raw_offset(raw, start + used)
        return result

    def append_rules(self, raw):
        packed = compact(raw)
        for rule in self.rules.values():
            if rule["operator"] != "append_table" or not self.enabled(rule["id"]):
                continue
            if any(packed.startswith(compact(item)) for item in rule.get("excludes", [])):
                continue
            for prefix in rule["prefixes"]:
                stem = compact(prefix)
                if not packed.startswith(stem) or len(packed) <= len(stem) or not self.base.contains(prefix):
                    continue
                table_id = rule["table_ids"][0]
                tail = packed[len(stem):]
                result = self.from_base(prefix, len(prefix))
                if table_id == "china_region":
                    used = self.add_china_region(result, tail, rule["id"])
                else:
                    key = longest_key(self.tables[table_id]["entries"], tail)
                    if not key:
                        continue
                    self.add_table(result, table_id, key, rule["id"])
                    used = len(key)
                if used:
                    result.consumed = raw_offset(raw, len(stem) + used)
                    yield result

    def imitate_rules(self, raw):
        packed = compact(raw)
        for rule in self.rules.values():
            if rule["operator"] != "imitate" or not self.enabled(rule["id"]):
                continue
            prefix, target_prefix = rule["prefix"], rule["target"]
            if not packed.startswith(compact(prefix)) or not self.base.contains(prefix):
                continue
            suffix = packed[len(compact(prefix)):]
            target = self.base.longest_prefix(format_number(compact(target_prefix) + suffix))
            if not target or len(compact(target)) <= len(compact(target_prefix)):
                continue
            result = self.from_base(prefix)
            target_path = self.base.path(target)
            after_anchor = False
            for node in target_path:
                if node["code"] == target_prefix:
                    after_anchor = True
                elif after_anchor:
                    result.node(node["name"], "", rule["id"])
            used = len(compact(prefix)) + len(compact(target)) - len(compact(target_prefix))
            result.consumed = raw_offset(raw, used)
            result.notes.append(f"{prefix}仿{target_prefix}：保留原库{prefix}父链，仅采用已列相对细目。")
            yield result

    def number(self, raw):
        if self.base.contains(raw):
            return self.from_base(raw)
        matched = self.base.longest_prefix(raw)
        candidates = [self.from_base(matched)] if matched else []
        for result in (self.literature(raw), self.biography(raw)):
            if result:
                candidates.append(result)
        candidates.extend(self.append_rules(raw))
        candidates.extend(self.imitate_rules(raw))
        candidates.extend(self.zero_table_rules(raw))
        # 补充分解先比较消费长度，不会被I/K一级大类抢先截断。
        return max(candidates, key=lambda item: (item.consumed, len(item.rules)), default=None)

    def zero_table_rules(self, raw):
        packed = compact(raw)
        for rule in self.rules.values():
            if rule["operator"] != "zero_table_imitation" or not self.enabled(rule["id"]):
                continue
            if not re.match(rule["scope_regex"], packed):
                continue
            table_id = rule["table_ids"][0]
            table = self.tables[table_id]
            for split in range(3, len(packed) - 1):
                anchor = format_number(packed[:split])
                if packed[split] != "0" or not self.base.contains(anchor):
                    continue
                tail = packed[split + 1:]
                key = longest_key(table["entries"], tail)
                if not key:
                    continue
                result = self.from_base(anchor)
                for length in range(1, len(key)):
                    parent = key[:length]
                    if parent in table["entries"]:
                        self.add_table(result, table_id, parent, rule["id"])
                self.add_table(result, table_id, key, rule["id"])
                result.notes.append(f"{anchor}按S51/59注仿S50：0后采用一般性问题的相对细目，不新增替代原库的主类。")
                used = len(key)
                if key in table.get("region_subdivision", []) and len(tail) > used:
                    used += self.add_world_region(result, tail[used:], "C5-WORLD-REGION")
                result.consumed = raw_offset(raw, split + 1 + used)
                yield result

    def marked(self, normalized, result):
        # 原库已列出的带符号专类也参与重复标记检查。
        seen = set(char for char in normalized[:result.consumed] if char in '-=("<')
        while result.consumed < len(normalized):
            tail = normalized[result.consumed:]
            marker = tail[0]
            if marker in seen:
                result.warnings.append("同一类复分标记重复，未继续套用。")
                return
            seen.add(marker)
            if marker in '("<':
                close = {'(': ')', '"': '"', '<': '>'}[marker]
                end = tail.find(close, 1)
                if end < 0:
                    result.warnings.append("复分标记未闭合。")
                    return
                value = compact(tail[1:end])
                if not re.fullmatch(r"\d+(?:[A-Z]{2})?", value):
                    return
                # 括号表号是整体；不能把局部解释当作整个地区已解析。
                trial = copy.deepcopy(result)
                if marker == '(' and self.enabled("C5-WORLD-REGION"):
                    used = self.add_world_region(trial, value, "C5-WORLD-REGION")
                elif marker == '"' and self.enabled("C5-WORLD-ETHNIC"):
                    used = self.add_ethnic(trial, value, "C5-WORLD-ETHNIC")
                elif marker == '<' and self.enabled("C5-ENVIRONMENT") and value in self.tables["environment"]["entries"]:
                    self.add_table(trial, "environment", value, "C5-ENVIRONMENT")
                    used = len(value)
                else:
                    return
                if used != len(value):
                    return
                result.__dict__.update(trial.__dict__)
                result.consumed += end + 1
            elif marker in "-=":
                match = re.match(r"[-=](\d+(?:\.\d+)*)", tail)
                if not match:
                    return
                raw_value = match.group(1)
                value = compact(raw_value)
                if marker == '=':
                    china = result.country == "china"
                    table_id = "china_time" if china else "international_time"
                    rule_id = "C5-CHINA-TIME" if china else "C5-INTERNATIONAL-TIME"
                    if not self.enabled(rule_id):
                        return
                    key = longest_key(self.tables[table_id]["entries"], value)
                    if not key:
                        return
                    self.add_table(result, table_id, key, rule_id)
                    used = len(key)
                else:
                    if not self.enabled("C5-GENERAL"):
                        return
                    table = self.tables["general"]
                    key = longest_key(table["entries"], value)
                    if not key:
                        return
                    dedicated = result.context.get("foreign_literature") and not result.context.get("literature_genre")
                    overrides = self.tables["foreign_literature"]["general_overrides"]
                    if dedicated and key in overrides:
                        result.node(overrides[key], "", "C5-I-COUNTRY", "foreign_literature", "-" + key)
                        result.notes.append("优先使用I3/7的专用总论类目，不套通用同号名称。")
                    else:
                        self.add_table(result, "general", key, "C5-GENERAL")
                    used = len(key)
                    if key in table["region_subdivision"] and len(value) > used and not dedicated:
                        used += self.add_world_region(result, value[used:], "C5-WORLD-REGION")
                result.consumed += 1 + raw_offset(raw_value, used)
                if used < len(value):
                    return
            else:
                # 冒号组配、多个分类号、未核对标记都保留，不跨过它们继续猜。
                return

    def parse(self, raw, normalized):
        if self.base.contains(normalized):
            result = self.from_base(normalized)
        else:
            match = re.match(r"[A-Z]{1,2}\d*(?:\.\d+)*", normalized)
            if not match:
                return empty_result(raw, normalized, "invalid")
            number = match.group()
            result = self.number(number)
            # 主表中带-、+等符号的专类优先于通用复分解释。
            explicit_prefix = self.base.longest_prefix(normalized)
            boundary = normalized[len(explicit_prefix):len(explicit_prefix) + 1]
            if explicit_prefix and boundary not in "0123456789." and (result is None or len(explicit_prefix) > result.consumed):
                result = self.from_base(explicit_prefix)
            if result is None:
                return empty_result(raw, normalized, "unknown")
            if result.consumed >= len(number):
                self.marked(normalized, result)
        for exception in self.registry.get("exceptions", []):
            if (normalized == exception["code"] or result.base_code == exception["code"]) and self.enabled(exception["rule_id"]):
                result.mark(exception["rule_id"])
                result.flag(exception["code_status"], exception["note"])
        unparsed = normalized[result.consumed:]
        status = "partial" if unparsed else ("supplemented" if result.rules else "exact")
        if "/" in normalized or normalized.startswith(("[", "{")):
            result.code_status = "reference_only"
        if unparsed:
            result.warnings.append("只显示已确认部分；剩余号码未命中已审核规则，不代表原始分类号错误。")
        if self.registry_warning:
            result.warnings.append(self.registry_warning)
        sources = [{"kind": "dependency", "name": "chinese-library-classification", "version": self.base.version}]
        for rule_id in result.rules:
            sources.append({"kind": "rule", "rule_id": rule_id, "edition": 5, "pdf_pages": self.rules[rule_id]["pdf_pages"]})
        for table_id in result.tables:
            table = self.tables[table_id]
            sources.append({"kind": "table", "table_id": table_id, "edition": 5, "pdf_pages": table["pdf_pages"]})
        names = [node["name"] for node in result.nodes]
        return {
            "code": raw, "normalized_code": normalized, "name": names[-1] if names else "",
            "path": names, "path_str": " > ".join(names), "path_nodes": result.nodes,
            "status": status, "status_label": STATUS_LABELS[status], "complete": not unparsed,
            "code_status": result.code_status, "code_status_label": VALIDITY_LABELS[result.code_status],
            "base_code": result.base_code, "matched_code": normalized[:result.consumed], "unparsed": unparsed,
            "rule_ids": result.rules, "explanations": result.notes, "warnings": result.warnings,
            "sources": sources, "rules_version": self.registry["version"],
        }


def empty_result(raw, normalized, status):
    return {"code": raw, "normalized_code": normalized, "name": "", "path": [], "path_str": "",
            "path_nodes": [], "status": status, "status_label": STATUS_LABELS[status], "complete": False,
            "code_status": "not_assessed", "code_status_label": VALIDITY_LABELS["not_assessed"],
            "base_code": "", "matched_code": "", "unparsed": normalized,
            "rule_ids": [], "explanations": [], "warnings": [], "sources": [], "rules_version": ""}


def parse_clc(code):
    raw = "" if code is None else str(code)
    # 只规范解析副本；原号含空白、大小写及全角符号始终保留。
    normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw)).upper()
    normalized = normalized.translate(str.maketrans({"“": '"', "”": '"', "〈": "<", "〉": ">", "−": "-", "—": "-"}))
    if not normalized:
        return empty_result(raw, normalized, "empty")
    if len(normalized) > 256 or ".." in normalized:
        return empty_result(raw, normalized, "invalid")
    try:
        return RuleParser().parse(raw, normalized)
    except Exception as error:
        # 分类层故障不应让已查到的书目变成网络失败，也不能伪装为一级类目。
        LOGGER.exception("本地分类解析失败")
        result = empty_result(raw, normalized, "unavailable")
        result["warnings"].append(f"本地分类数据或规则读取失败：{type(error).__name__}")
        return result
