# clc_parser.py
# 中图分类号解析模块

from chinese_library_classification import Chineselibraryclassification

# 全局初始化 CLC 实例（只加载一次数据）
_clc = Chineselibraryclassification()

# 内置一级大类字典，作为兜底
_TOP_LEVEL_CLASSES = {
    "A": "马克思主义、列宁主义、毛泽东思想、邓小平理论",
    "B": "哲学、宗教",
    "C": "社会科学总论",
    "D": "政治、法律",
    "E": "军事",
    "F": "经济",
    "G": "文化、科学、教育、体育",
    "H": "语言、文字",
    "I": "文学",
    "J": "艺术",
    "K": "历史、地理",
    "N": "自然科学总论",
    "O": "数理科学和化学",
    "P": "天文学、地球科学",
    "Q": "生物科学",
    "R": "医药、卫生",
    "S": "农业科学",
    "T": "工业技术",
    "U": "交通运输",
    "V": "航空、航天",
    "X": "环境科学、安全科学",
    "Z": "综合性图书",
}


def _find_best_match(code):
    """
    逐级向上截断分类号，直到找到库中存在的匹配。
    例如 K256.707 → K256.70 → K256.7 → K256 → K25 → K2 → K
    返回 (匹配到的分类号, info字典) 或 (None, None)。
    """
    current = code
    while current:
        try:
            info = _clc.num2info(current)
            if info and info.get('name'):
                return current, info
        except Exception:
            pass
        # 截短一位
        if '.' in current and len(current.split('.')[-1]) > 0:
            # 小数点后还有字符，从末尾去掉一位
            current = current[:-1]
            # 如果小数点后已空，去掉小数点
            if current.endswith('.'):
                current = current[:-1]
        elif len(current) > 1:
            current = current[:-1]
        else:
            break
    return None, None


def parse_clc(code):
    """
    解析中图分类号，返回完整的层级路径信息。

    参数:
        code: 中图分类号字符串，如 "TP311.12" 或 "K256.707"

    返回:
        字典，包含:
        - code: 原始分类号
        - name: 分类名称（最细粒度能匹配到的）
        - path: 层级路径列表，从大类到具体分类
        - path_str: 层级路径字符串，用 " > " 连接
        如果无法解析，name 和 path 为空。
    """
    if not code or not code.strip():
        return {
            "code": code or "",
            "name": "",
            "path": [],
            "path_str": ""
        }

    code = code.strip()

    try:
        # 逐级查找最佳匹配
        matched_code, info = _find_best_match(code)

        if not matched_code or not info:
            # 全部查不到，用内置字典兜底
            raise ValueError("库中无匹配")

        current_name = info.get('name', '')

        # 获取所有上级分类
        upper_levels = _clc.num2upper(matched_code)

        # 构建完整路径（从大类到当前分类）
        # num2upper 返回格式: [['K25', '半殖民地...'], ['K2', '中国史'], ['K', '历史、地理']]
        # 顺序是从近到远，需要反转
        path = []
        if upper_levels:
            for level_code, level_name in reversed(upper_levels):
                path.append(level_name)

        # 添加当前匹配到的分类名称
        if current_name:
            path.append(current_name)

        return {
            "code": code,
            "name": current_name,
            "path": path,
            "path_str": " > ".join(path) if path else ""
        }

    except Exception:
        # 如果全部失败，用内置字典进行一级大类解析
        top_letter = code[0].upper()
        top_name = _TOP_LEVEL_CLASSES.get(top_letter, "")

        if top_name:
            return {
                "code": code,
                "name": top_name,
                "path": [top_name],
                "path_str": top_name
            }

        return {
            "code": code,
            "name": "",
            "path": [],
            "path_str": ""
        }


def get_top_class_name(code):
    """
    获取分类号对应的一级大类名称。
    如 "TP311" -> "工业技术"
    """
    if not code:
        return ""
    top_letter = code[0].upper()
    return _TOP_LEVEL_CLASSES.get(top_letter, "")
