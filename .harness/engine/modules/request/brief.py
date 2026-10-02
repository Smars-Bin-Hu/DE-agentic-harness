"""knowledge-brief.md: one finding per line, each with its source. A line without a source is refused."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .layout import CommandError

ENTRY = re.compile(r"^[-*]\s+(?P<claim>.+?)\s*\[来源[:：]\s*(?P<source>[^\]]+?)\s*\]\s*$")
FORMAT_HINT = "每个条目一行：`- 结论 [来源: 文件路径#章节]`。标题（# 开头）和空行可以有，其他内容不行。"


def parse(text: str, policy: Dict[str, Any]) -> List[str]:
    """The entries (whole lines, trimmed). Raises CommandError that says which line is wrong."""
    limits = policy["brief"]
    size = len(text.encode("utf-8"))
    if size > limits["max_bytes"]:
        raise CommandError(f"brief 太大（{size} 字节，上限 {limits['max_bytes']}）。只留和本请求有关的结论，再提交。")
    entries: List[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        found = ENTRY.match(stripped)
        if not found or not found.group("claim").strip() or not found.group("source").strip():
            raise CommandError(f"brief 第 {number} 行没有来源或格式不对：{stripped[:60]}。{FORMAT_HINT}")
        entries.append(stripped)
    if not entries:
        raise CommandError(f"brief 里没有任何条目。{FORMAT_HINT}")
    if len(entries) > limits["max_entries"]:
        raise CommandError(f"brief 条目太多（{len(entries)} 条，上限 {limits['max_entries']}）。合并或删掉不相关的。")
    return entries


def entries_of(text: str) -> List[str]:
    """Entries of a stored brief or snapshot, no limits (it was valid when it was saved)."""
    return [line.strip() for line in text.splitlines() if ENTRY.match(line.strip())]


def delta(old_text: str, new_text: str) -> List[str]:
    """Entries in the new brief that the old one did not have: added, or changed."""
    before = set(entries_of(old_text))
    return [entry for entry in entries_of(new_text) if entry not in before]
