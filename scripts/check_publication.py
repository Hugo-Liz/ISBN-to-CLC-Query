"""只读检查Git暂存区的发布文件；仅报告位置和风险类型，不打印敏感值。"""

import fnmatch
import io
import json
import re
import subprocess
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from scripts.index_clc_rules import public_index


BLOCKED_PARTS = {".git", ".venv", "venv", ".agents", ".codex", "private", "data",
                 "uploads", "tmp", "output", "logs", "__pycache__"}
BLOCKED_NAMES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.pdf",
                 "*.sqlite*", "*.db", "*.db-*", "*.log", "*.har", "*.pyc")
PATTERNS = {
    "个人目录": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+(?:/|\b)|[A-Z]:\\Users\\[^\\\s]+"),
    "本机临时路径": re.compile(r"/(?:private/)?var/folders/"),
    "GitHub凭据": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "API凭据": re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b"),
    "私钥": re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    "URL内嵌凭据": re.compile(r"https?://[^\s/:@]+:[^\s/@]+@"),
    "凭据赋值": re.compile(r"(?i)\b(?:api_key|access_token|secret_key|password)\s*[:=]\s*['\"][A-Za-z0-9_+/=-]{12,}['\"]"),
    "来源文件标记": re.compile(r"(?i)z[-](?:library|lib[.]sk)|1lib[.]sk"),
}
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
PUBLIC_EMAIL_DOMAINS = {"users.noreply.github.com", "noreply.github.com", "example.com", "example.org", "example.invalid"}


def scan_text(text):
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        findings.extend((number, label) for label, pattern in PATTERNS.items() if pattern.search(line))
        if any(not any(match.group(1).lower() == domain or match.group(1).lower().endswith("." + domain)
                       for domain in PUBLIC_EMAIL_DOMAINS) for match in EMAIL.finditer(line)):
            findings.append((number, "非示例/隐私邮箱"))
    return findings


def scan_file(path, data):
    relative = PurePosixPath(path)
    if any(part in BLOCKED_PARTS for part in relative.parts):
        return [(0, "本机/运行时目录")]
    if relative.name != ".env.example" and any(fnmatch.fnmatch(relative.name.lower(), pattern) for pattern in BLOCKED_NAMES):
        return [(0, "禁止发布的文件类型")]
    if relative.suffix.lower() == ".xlsx":
        if path != "static/批量查询模板.xlsx":
            return [(0, "非公开模板的工作簿")]
        findings = []
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.namelist():
                if member.endswith((".xml", ".rels")):
                    content = archive.read(member).decode("utf-8")
                    findings.extend(scan_text(content))
                    if "externalLinks/" in member or 'TargetMode="External"' in content:
                        findings.append((0, "工作簿外部链接"))
                    if member == "docProps/core.xml":
                        for element in ElementTree.fromstring(content):
                            if element.tag.split("}")[-1] in {"creator", "lastModifiedBy"}:
                                if element.text and element.text not in {"openpyxl"}:
                                    findings.append((0, "需复核的工作簿作者元数据"))
        return findings
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [(0, "需人工复核的二进制文件")]
    findings = scan_text(text)
    if path == "clc_rules/inventory.json":
        index = json.loads(text)
        if index != public_index(index):
            findings.append((0, "索引包含非公开字段"))
    return findings


def main():
    records = subprocess.check_output(["git", "ls-files", "--stage", "-z"]).split(b"\0")
    checked, findings = 0, []
    for record in records:
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, oid, stage = metadata.split()
        path = raw_path.decode("utf-8")
        if stage != b"0" or mode not in {b"100644", b"100755"}:
            findings.append((path, 0, "非普通文件或未解决冲突，需人工复核"))
            continue
        data = subprocess.check_output(["git", "cat-file", "blob", oid.decode("ascii")])
        findings.extend((path, line, label) for line, label in scan_file(path, data))
        checked += 1
    for path, line, label in findings:
        print(f"{path}:{line}: {label}（内容已隐藏）")
    print(f"暂存区检查：{checked} 个文件，{len(findings)} 个待处理项。")
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
