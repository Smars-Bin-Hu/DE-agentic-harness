"""`report`: one Markdown page about a request, from request.json, the handoffs and the hook log of its session.

The page lists facts. It does not judge, suggest changes or draft a PR. It is written to .workspace/reports/<request id>.md
(git ignores that folder) when the request is concluded, and again whenever `report` runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logs import read_lines, read_session, session_files

from . import layout, ops, store

REPORTS_DIR = ".workspace/reports"
SUMMARY_LINES = 6
LOG_ROWS = 40
REASON_CHARS = 100

RESULT_TEXT = {
    "accepted": "已通过。reviewer 通过，结果已验收。",
    "hitl": "进入 HITL：需要人来决定。",
    "abandoned": "已放弃。",
    "open": "进行中，还没有收尾。",
}
PROMOTE_TEXT = {"none": "没有回写。", "dry_run": "已生成计划，没有回写。", "done": "已回写到仓库。"}


def report_path(root: Path, request_id: str) -> Path:
    return root / REPORTS_DIR / f"{request_id}.md"


def cut(text: str, limit: int) -> str:
    one_line = " ".join(str(text).split())
    return one_line if len(one_line) <= limit else one_line[:limit] + "…"


def cell(text: str) -> str:
    return cut(text, REASON_CHARS).replace("|", "\\|")


def read_handoff(root: Path, directory: Path, number: int, role: str) -> Optional[Dict[str, Any]]:
    path = layout.handoff_file(directory, number, role)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summary_text(text: str) -> List[str]:
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    kept = lines[:SUMMARY_LINES]
    if len(lines) > SUMMARY_LINES:
        kept.append(f"（还有 {len(lines) - SUMMARY_LINES} 行，见 handoff.json）")
    return kept


def head_section(data: Dict[str, Any], limit: int) -> List[str]:
    promote = data["promote"]
    lines = [
        f"# 请求报告：{data['title']}",
        "",
        f"- 请求 id：{data['request_id']}",
        f"- 状态：{data['status']}" + (f"（{data['status_reason']}）" if data.get("status_reason") else ""),
        f"- 创建：{data['created_at']}",
        f"- 更新：{data['updated_at']}",
        f"- 会话：{data.get('session_id', '')}（{data.get('surface', '')}）",
        f"- 轮数：{data['attempt']} / 上限 {limit}",
        "",
        "## 结果",
        "",
        RESULT_TEXT.get(data["status"], data["status"]),
        f"回写：{PROMOTE_TEXT.get(promote['state'], promote['state'])}",
    ]
    for item in promote.get("files", []):
        lines.append(f"- {item['action']} {item['path']}")
    return lines


def attempts_section(root: Path, directory: Path, data: Dict[str, Any]) -> List[str]:
    if not data["attempts"]:
        return ["", "## 轮次", "", "还没有开过一轮。"]
    lines = ["", "## 轮次", "", "| 轮 | builder | reviewer | 超过上限，人同意继续 |", "| --- | --- | --- | --- |"]
    for item in data["attempts"]:
        handoffs = item["handoffs"]
        lines.append(
            f"| {item['n']} | {handoffs.get('builder', '未交')} | {handoffs.get('reviewer', '未交')} | {cell(item['human_approved']) or '-'} |"
        )
    lines += ["", "## 每轮的交接"]
    for item in data["attempts"]:
        lines += ["", f"### 第 {item['n']} 轮"]
        found = False
        for role in layout.ROLES:
            handoff = read_handoff(root, directory, item["n"], role)
            if handoff is None:
                continue
            found = True
            lines += ["", f"**{role}：{handoff['status']}**", ""]
            lines += [f"> {line}" for line in summary_text(handoff.get("summary", ""))] + [""]
            for label, key in (("成果", "outputs"), ("证据", "evidence")):
                if handoff.get(key):
                    lines.append(f"- {label}：" + "、".join(handoff[key]))
            for blocker in handoff.get("blockers", []):
                lines.append(f"- 问题：{blocker}")
            if handoff.get("next"):
                lines.append(f"- 建议：{handoff['next']}")
            for addition in handoff.get("kb_additions", []):
                lines.append(f"- 查到的知识：{addition}")
        if not found:
            lines += ["", "这一轮没有交接。"]
    return lines


def why_section(root: Path, directory: Path, data: Dict[str, Any], limit: int) -> List[str]:
    """Only for a request that did not end well: the facts behind it."""
    if data["status"] not in ("hitl", "abandoned"):
        return []
    lines = ["", "## 为什么是 " + data["status"], "", f"- 写下的原因：{data.get('status_reason') or '（没有写）'}"]
    lines.append(f"- 做了 {data['attempt']} 轮，上限 {limit}。" + ("到了上限。" if data["attempt"] >= limit else ""))
    if data["attempts"]:
        last = data["attempts"][-1]
        for role in layout.ROLES:
            handoff = read_handoff(root, directory, last["n"], role)
            if handoff and handoff["status"] != "passed":
                lines.append(f"- 第 {last['n']} 轮 {role} 是 {handoff['status']}：" + ("；".join(handoff.get("blockers", [])) or "没写问题"))
    return lines


def child_sessions(root: Path, surface: str, session_id: str, since: str) -> List[Dict[str, Any]]:
    """SDK engine: a subagent runs in a session of its own. Those logs name the session that called them."""
    found: List[Dict[str, Any]] = []
    for found_surface, path in session_files(root):
        if found_surface != surface or path.stem == session_id:
            continue
        rows = read_lines(path)
        if rows and rows[0].get("parent_session_id") == session_id and rows[-1].get("at", "") >= since:
            found.append({"session_id": path.stem, "rows": rows})
    return found


def log_section(root: Path, data: Dict[str, Any]) -> List[str]:
    session_id, surface = data.get("session_id", ""), data.get("surface", "vscode")
    rows = read_session(root, surface, session_id)
    lines = ["", "## hook 日志（会话 " + session_id + "）", ""]
    if not rows:
        return lines + ["没有找到这个会话的日志（observe 没开，或日志已被 `logs prune` 清理）。"]
    children = child_sessions(root, surface, session_id, data["created_at"])
    every = rows + [row for child in children for row in child["rows"]]
    since = data["created_at"]
    window = [row for row in every if row.get("at", "") >= since]
    counted = {
        "hook 调用": len(window),
        "拒绝（deny）": sum(1 for row in window if row.get("decision") == "deny"),
        "要人确认（ask）": sum(1 for row in window if row.get("decision") == "ask"),
        "Stop 被拦": sum(1 for row in window if row.get("decision") == "block"),
        "子 agent 启动": sum(1 for row in window if row.get("event") == "SubagentStart"),
    }
    lines.append("请求创建之后：" + "，".join(f"{name} {number}" for name, number in counted.items()) + "。")
    if children:
        lines.append(f"子 agent 另有 {len(children)} 个会话（SDK 引擎），已一起统计。")
    refusals = [row for row in window if row.get("decision") in ("deny", "ask", "block")]
    if not refusals:
        return lines + ["", "没有拒绝和确认记录。"]
    lines += ["", "拒绝和确认记录（时间是 UTC）：", "", "| 时间 | 事件 | 工具 | 决定 | 谁 | 原因 | 对象 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in refusals[:LOG_ROWS]:
        target = row.get("target") or {}
        about = "、".join(target.get("paths", [])) or target.get("command", "")
        lines.append(
            f"| {row.get('at', '')[11:19]} | {row.get('event', '')} | {row.get('tool_name', '') or '-'} | {row.get('decision', '')}"
            f" | {row.get('judge', '')}:{','.join(row.get('by') or [])} | {cell(row.get('reason', ''))} | {cell(about) or '-'} |"
        )
    if len(refusals) > LOG_ROWS:
        lines.append(f"\n（还有 {len(refusals) - LOG_ROWS} 条，见会话日志。）")
    return lines


def render(root: Path, data: Dict[str, Any]) -> str:
    directory = layout.request_dir(root, data["request_id"])
    limit = ops.policy(root)["max_attempts"]
    lines = head_section(data, limit) + attempts_section(root, directory, data) + why_section(root, directory, data, limit) + log_section(root, data)
    return "\n".join(lines) + "\n"


def generate(root: Path, request_id: str = "") -> Dict[str, Any]:
    """Write the report of one request (the newest request when none is named) and say where it is."""
    if not request_id:
        listed = ops.list_requests(root)["requests"]
        if not listed:
            raise layout.CommandError("还没有请求。先用 `request new` 建一个。")
        request_id = listed[0]["request_id"]
    data = store.read_request(root, request_id)
    path = report_path(root, request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render(root, data)
    path.write_text(text, encoding="utf-8")
    return {"request_id": request_id, "report": path.relative_to(root).as_posix(), "status": data["status"], "lines": text.count("\n")}
