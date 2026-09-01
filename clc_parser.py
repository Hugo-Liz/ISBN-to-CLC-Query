"""兼容原调用入口；基础类目由原依赖与第五版官网覆盖数据合并得到。"""

from clc_rules.engine import parse_clc


def get_top_class_name(code):
    """返回合并基础数据中的一级大类名称。"""
    if not code or not str(code).strip():
        return ""
    from clc_rules.base import get_base
    return get_base().records.get(str(code).strip()[0].upper(), {}).get("name", "")
