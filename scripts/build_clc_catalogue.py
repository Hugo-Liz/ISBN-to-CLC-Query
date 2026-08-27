"""从规则、核对记录与全书候选生成可重复的覆盖报告，不夸大完成率。"""

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build_catalogue(root=ROOT):
    folder = root / "clc_rules"
    registry = json.loads((folder / "rules.json").read_text(encoding="utf-8"))
    tables = json.loads((folder / "tables.json").read_text(encoding="utf-8"))["tables"]
    index = json.loads((folder / "inventory.json").read_text(encoding="utf-8"))
    reviews = json.loads((folder / "review_map.json").read_text(encoding="utf-8"))
    candidate_ids = {item["id"] for item in index["candidates"]}
    rule_ids = {item["id"] for item in registry["rules"]}
    reviewed = set()
    for finding in reviews["findings"]:
        if finding["candidate_id"] not in candidate_ids or not set(finding["rule_ids"]) <= rule_ids:
            raise ValueError("核对记录引用了不存在的候选或规则")
        reviewed.add(finding["candidate_id"])
    counts = Counter(rule["implementation_status"] for rule in registry["rules"])
    low_text = [str(page["pdf_page"]) for page in index["page_audit"] if page["text_chars"] < 200]
    lines = [
        "# 第五版复分规则：实施与覆盖报告", "",
        "由 `scripts/build_clc_catalogue.py` 生成。数据来源为用户提供的第五版 PDF；PDF 页与纸面页分开标识。",
        "原库仍是 `chinese-library-classification==0.0.1`；本项目只增加复分数据、作用域与解释，不替换主分类库。", "",
        "公开索引仅保留规则定位与审核元数据；源PDF、OCR片段、文件指纹和本机路径不随项目发布。", "",
        "## 当前是分阶段实施，不是全书完成", "",
        f"- 全书机器扫描：{index['page_count']} 页，{index['candidate_count']} 个候选行（不是独立规则数）。",
        f"- 已定位核对并关联规则的候选行：{len(reviewed)}；其余 {index['candidate_count'] - len(reviewed)} 行仍待审核。",
        f"- 已登记可执行规则组：{len(registry['rules'])}，其中 {counts['implemented']} 组在声明范围内实现，{counts['partial']} 组仅部分实现。",
        f"- 补充表：{len(tables)} 张，含8种通用表与专用表；共 {sum(len(t['entries']) for t in tables.values())} 个已录入条目，不代表这些表都已收全。",
        f"- 规则样例断言：{sum(len(r['cases']) for r in registry['rules'])} 个；由自动测试逐个检查，不能据此推算全书覆盖率。",
        "- `inventory.json` 是原始发现台账，原始状态保持待审核；有效审核关联见 `review_map.json`，不得仅以扫描状态判断是否支持。",
        "- 解析完整与编目有效性分开；除已核对的停用、交替、历史和专类例外，号码有效性默认未鉴定。", "",
        "原库共有45,785条记录，其中45,757条有类名、28条类名为空。所有父链已回归比对；有类名的精确项保留原路径，空类名项明确部分解析。", "",
        "## 可执行规则组", "",
        "| 规则 | 作用域 | 实现 | PDF页（纸面页） |", "|---|---|---|---|",
    ]
    for rule in registry["rules"]:
        pages = "、".join(f"{p}（{p - 21}）" for p in rule["pdf_pages"])
        state = "声明范围内已实现" if rule["implementation_status"] == "implemented" else "部分实现"
        lines.append(f"| `{rule['id']}` {rule['title']} | {rule['scope']} | {state} | {pages} |")
    lines += ["", "## 每组边界", ""]
    for rule in registry["rules"]:
        lines.append(f"- `{rule['id']}`：{rule.get('limits', '仅限上表列出的已审核作用域；其他相似类目不得自动继承。')}")
    lines += ["", "## 表数据覆盖", "", "| 表 | 已录入条目 | 范围 |", "|---|---:|---|"]
    lines += [f"| {table['name']} | {len(table['entries'])} | {table['coverage']} |" for table in tables.values()]
    lines += ["", "## 核对记录", "", "| 候选行 | 已关联规则 | 核对说明 |", "|---|---|---|"]
    lines += [f"| `{finding['candidate_id']}` | {'、'.join(finding['rule_ids'])} | {finding['note']} |" for finding in reviews["findings"]]
    lines += ["", "## 未完成项", ""]
    lines += [f"- {item}" for item in reviews["remaining_work"]]
    lines += ["", "低文本页（少于200个非空白字符）仍需逐页确认是否空白或OCR失败：", "", "、".join(low_text), "",
              "未知尾缀、未审规则与数据未录入均返回部分解析并保留原号，不生成听起来合理的虚构路径。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="检查已生成文档是否与数据一致")
    args = parser.parse_args()
    output = ROOT / "docs" / "clc-rule-coverage.md"
    text = build_catalogue()
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != text:
            raise SystemExit("规则覆盖文档已过期，请重新生成。")
        print("规则覆盖文档与数据一致。")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(output)


if __name__ == "__main__":
    main()
