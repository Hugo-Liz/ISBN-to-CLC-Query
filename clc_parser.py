"""兼容原调用入口；主分类数据仍取自 chinese-library-classification。"""

from clc_rules.engine import parse_clc


def get_top_class_name(code):
    """返回原依赖库中的一级大类名称。"""
    if not code or not str(code).strip():
        return ""
    from clc_rules.base import get_base
    return get_base().records.get(str(code).strip()[0].upper(), {}).get("name", "")
