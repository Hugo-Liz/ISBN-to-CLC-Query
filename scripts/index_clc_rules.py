"""从本机 PDF 的 pdftotext -layout 输出建立候选索引，不把 OCR 全文收入项目。

这里只发现线索，不能自动把 OCR 片段提升为已审核、可执行规则。
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


PATTERNS = {
    "依表": re.compile(r"依[^。；\n]{0,65}?表\s*分"),
    "仿分": re.compile(r"仿[^。；\n]{0,65}?分"),
    "专用表": re.compile(r"下表|专[用类]复分|复分表"),
    "复分说明": re.compile(r"复分|仿分|组配|交替类目|停用"),
    "复分标记": re.compile(r"[①②③④⑤⑥⑦⑧⑨]"),
    "范围线索": re.compile(r"[A-Z][\d.]+/[A-Z\d.]+"),
    "停用线索": re.compile(r"[\{｛][^\}\n]{1,35}[\}｝]"),
}

SECTIONS = [
    (1, "前言"), (22, "A"), (28, "B"), (44, "C"), (52, "D"),
    (86, "E"), (98, "F"), (140, "G"), (174, "H"), (188, "I"),
    (198, "J"), (220, "K"), (258, "N"), (262, "O"), (302, "P"),
    (342, "Q"), (400, "R"), (468, "S"), (546, "T"), (924, "U"),
    (980, "V"), (1000, "X"), (1008, "Z"), (1012, "通用复分表"),
    (1036, "附后"),
]

SOURCE_LABEL = "中国图书馆分类法（第五版），1041页参考PDF；公开索引不含源文件信息"
INDEX_WARNING = "候选行不是独立规则数；OCR、跨页、双栏与继承关系均可能漏检。未审核线索绝不直接执行。"


def public_index(index):
    """按白名单生成可发布索引，不携带OCR片段、文件名、路径或指纹。"""
    candidate_keys = ("id", "pdf_page", "printed_page", "section", "line", "kinds", "review_status", "rule_ids")
    audit_keys = ("pdf_page", "section", "text_chars", "candidate_lines", "visual_review")
    return {
        "schema_version": index["schema_version"], "edition": index["edition"],
        "source": SOURCE_LABEL, "warning": INDEX_WARNING,
        "page_count": index["page_count"], "candidate_count": index["candidate_count"],
        "candidates": [{key: row[key] for key in candidate_keys} for row in index["candidates"]],
        "page_audit": [{key: row[key] for key in audit_keys} for row in index["page_audit"]],
    }


def section_for(page):
    return next(name for start, name in reversed(SECTIONS) if page >= start)


def build_index(text, pdf_sha256=None, include_private=False):
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    records, audit = [], []
    for page, content in enumerate(pages, 1):
        lines = content.splitlines()
        line_numbers = set()
        for number, line in enumerate(lines, 1):
            kinds = [key for key, pattern in PATTERNS.items() if pattern.search(line)]
            if not kinds:
                continue
            line_numbers.add(number)
            # 上下文只供定位；左右栏可能交错，必须回看原版页面。
            context = " ".join(lines[max(0, number - 2):number + 1])
            records.append({
                "id": f"C5-P{page:04d}-L{number:03d}",
                "pdf_page": page,
                "printed_page": page - 21 if 22 <= page <= 1035 else None,
                "section": section_for(page),
                "line": number,
                "kinds": kinds,
                "locator_hint": re.sub(r"\s+", " ", context).strip()[:180],
                "review_status": "pending",
                "rule_ids": [],
            })
        audit.append({
            "pdf_page": page,
            "section": section_for(page),
            "text_chars": len(re.sub(r"\s", "", content)),
            "candidate_lines": len(line_numbers),
            "visual_review": "pending",
        })
    index = {
        "schema_version": 1,
        "edition": 5,
        "pdf_sha256": pdf_sha256,
        "source": SOURCE_LABEL,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "warning": INDEX_WARNING,
        "page_count": len(pages),
        "candidate_count": len(records),
        "candidates": records,
        "page_audit": audit,
    }
    return index if include_private else public_index(index)


def render_markdown(index):
    counts = Counter(item["section"] for item in index["candidates"])
    lines = [
        "# 第五版全书规则候选台账", "",
        "此文件由 `scripts/index_clc_rules.py` 生成。它记录待审核线索，不代表全书规则已经实现。",
        "PDF、OCR片段及源文件指纹不随项目分发；页码指1041页参考PDF，正文纸面页码为PDF页减21。", "",
        f"机器扫描 {index['page_count']} 页，得到 {index['candidate_count']} 个候选行（非独立规则数）。",
        "依表、仿分、专用表、复分标记、范围和停用线索分别扫描；同一行合并。",
        "公开台账只保留定位元数据；相邻文字只在本机参考。左右栏、跨页及被OCR漏掉的标记仍须人工复核。", "",
        "## 分类分布", "", "| 类别 | 候选行 |", "|---|---:|",
    ]
    lines.extend(f"| {section} | {count} |" for section, count in counts.items())
    low = [str(item["pdf_page"]) for item in index["page_audit"] if item["text_chars"] < 200]
    lines.extend(["", "## 必须单独检查的低文本页", "", "、".join(low), "",
                  "低文本页可能是空白页，也可能是 OCR 失败；当前均保留待视觉复核状态。", "",
                  "## 候选位置", "", "全部候选的类型、页码、行号和审核状态保存在 `clc_rules/inventory.json`，不含OCR文字片段。", "",
                  "| 类别 | PDF 页 | 候选 ID | 线索类型 | 审核 |", "|---|---:|---|---|---|"])
    for item in index["candidates"]:
        lines.append(f"| {item['section']} | {item['pdf_page']} | {item['id']} | {'、'.join(item['kinds'])} | 待核对 |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text_path", type=Path, nargs="?")
    parser.add_argument("--public-from-index", type=Path, help="将现有本机索引按白名单脱敏，无需重读PDF")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--pdf-sha256", help="原PDF的SHA-256，可用shasum -a 256在本机取得")
    parser.add_argument("--include-private-locators", action="store_true", help="仅本机研究使用：保留OCR片段和指纹，不得提交")
    args = parser.parse_args()
    if bool(args.text_path) == bool(args.public_from_index):
        parser.error("请指定文字文件或--public-from-index，不能同时使用。")
    if args.public_from_index and (args.include_private_locators or args.pdf_sha256):
        parser.error("生成公开索引时不能附加私有定位信息或文件指纹。")
    # 为避免清空后续人工审核结果，索引默认不覆盖现有文件。
    if args.output.exists() or args.markdown.exists():
        parser.error("输出已存在；请生成到新路径并核对差异，不覆盖审核记录。")
    if args.pdf_sha256 and not re.fullmatch(r"[0-9a-f]{64}", args.pdf_sha256):
        parser.error("PDF指纹必须为64位小写十六进制SHA-256")
    if args.public_from_index:
        index = public_index(json.loads(args.public_from_index.read_text(encoding="utf-8")))
    else:
        index = build_index(args.text_path.read_text(encoding="utf-8"), args.pdf_sha256, args.include_private_locators)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(index), encoding="utf-8")
    print(json.dumps({"pages": index["page_count"], "candidates": index["candidate_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
