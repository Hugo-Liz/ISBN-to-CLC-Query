"""只读适配原库，复用其类目及父链，避免每次查号重读十余 MB JSON。"""

import json
from functools import lru_cache
from importlib import metadata, resources


class BaseIndex:
    def __init__(self, records, version="0.0.1"):
        self.records = records
        self.version = version

    def contains(self, code):
        return bool(self.records.get(code, {}).get("name"))

    def path(self, code):
        nodes, seen = [], set()
        while code is not None:
            if code in seen:
                raise ValueError("原库父链存在循环")
            seen.add(code)
            row = self.records[code]
            nodes.append({"code": code, "name": row["name"], "source": "base"})
            code = row["up_level"]
        return list(reversed(nodes))

    def longest_prefix(self, code):
        for length in range(len(code), 0, -1):
            candidate = code[:length]
            if not candidate.endswith(".") and self.contains(candidate):
                return candidate
        return ""


@lru_cache(maxsize=1)
def get_base():
    package = resources.files("chinese_library_classification")
    with package.joinpath("data", "data.json").open(encoding="utf-8") as stream:
        records = json.load(stream)
    if not isinstance(records, dict) or not all(
        isinstance(row, dict) and "name" in row and "up_level" in row
        for row in records.values()
    ):
        raise ValueError("原分类依赖的数据结构已变化，请检查适配层")
    return BaseIndex(records, metadata.version("chinese-library-classification"))
