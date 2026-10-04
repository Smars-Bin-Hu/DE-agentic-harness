"""`task report`: one Markdown page about an L2 task, from task.json, PLAN.md, DEV/ and the hook log of its session.

Like the request report it lists facts and judges nothing. It is written to .workspace/reports/task-<name>.md when the
task is closed, and again whenever `task report` runs. Earlier rounds of the same task stay on the page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core import tasks
from core.logs import read_session

from . import report, task as task_ops

PLAN_LINES = 120
EVENT_TEXT = {
    "start": "开始", "resume": "接着做", "new-round": "开新的一轮", "approve-plan": "人批准计划", "fetch": "取文件", "delete": "声明删除",
    "set-branch": "设分支名", "verify": "verifier 复核", "promote-dry-run": "回写计划（dry-run）", "approve-promote": "人批准回写", "promote": "回写到新分支",
    "promote-partial": "回写中途出错", "recover": "人恢复仓库", "close": "关闭",
}
PROMOTE_TEXT = {"none": "没有回写。", "dry_run": "已生成回写计划，没有回写。", "done": "已回写到目标仓库的新分支（没有提交）。", "partial": "回写中途出错，要人运行 task recover。"}


def report_path(root: Path, task: str) -> Path:
    return root / report.REPORTS_DIR / f"task-{task_ops.name_of(task)}.md"


def verdicts(root: Path, data: Dict[str, Any]) -> List[str]:
    """What the verifier said in this task's session since the round began (from the hook log)."""
    rows = read_session(root, data.get("surface", "vscode"), data.get("session_id", ""))
    since = data.get("round_started_at", data["created_at"])
    return [f"{row.get('at', '')[:19]} {row['verdict']}" for row in rows if row.get("judge") == "verifier" and row.get("verdict") and row.get("at", "") >= since]


def render(root: Path, task: str, data: Dict[str, Any]) -> str:
    promote = data["promote"]
    plan = data.get("plan") or {}
    approved_now = tasks.plan_approved(root, task, data)
    lines = [
        f"# 任务报告：{data['name']}",
        "",
        f"- 任务目录：{task}",
        f"- 状态：{data['status']}，第 {data['round']} 轮",
        f"- 创建：{data['created_at']}",
        f"- 更新：{data['updated_at']}",
        f"- 会话：{data.get('session_id', '')}（{data.get('surface', '')}）",
        "- 计划：" + (f"由人批准于 {plan['approved_at']}" + ("" if approved_now else "；之后计划又改过，现在的版本没有批准") if plan.get("approved_at") else "没有人的批准"),
    ]
    lines.append("- verifier 复核：" + {"on": "开启", "off": "关闭"}.get(tasks.verify_choice(data), "没有开启（默认）"))
    if data.get("branch"):
        lines.append(f"- 分支：{data['branch']}")
    lines += [f"- 目标仓库：{name}，{item['base_ref']} 在 {item['base_commit'][:12]}" for name, item in data.get("targets", {}).items()]
    lines += ["", "## 结果", "", f"回写：{PROMOTE_TEXT.get(promote['state'], promote['state'])}"]
    if promote.get("approved_at"):
        lines.append(f"- 回写由人批准于 {promote['approved_at']}")
    for item in promote.get("files", []):
        lines.append(f"- {item['action']} {item['path']}")
    if promote.get("patch"):
        lines.append(f"- 补丁：{promote['patch']}")
    items, _text = task_ops.changes(root, task, data)
    changed = [item for item in items if item["action"] != "unchanged"]
    lines += ["", "## DEV/ 里的改动", ""]
    if changed:
        lines += ["| 文件 | 动作 | 增 | 删 |", "| --- | --- | --- | --- |"]
        lines += [f"| {item['path']} | {item['action']} | {item['added']} | {item['removed']} |" for item in changed]
    else:
        lines.append("没有改动。")
    fetched = sorted(data.get("target_files", {}))
    if fetched:
        lines += ["", f"从 main 取过 {len(fetched)} 个文件：" + "、".join(fetched[:30]) + ("……" if len(fetched) > 30 else "")]
    said = verdicts(root, data)
    lines += ["", "## verifier 复核", ""] + ([f"- {item}" for item in said] if said else ["这一轮没有 verifier 的结论（没有开启，或没有调用）。"])
    lines += ["", "## 计划（PLAN.md）", ""]
    try:
        plan_lines = tasks.plan_file(root, task).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        plan_lines = []
    if plan_lines:
        lines += ["> " + line for line in plan_lines[:PLAN_LINES]]
        if len(plan_lines) > PLAN_LINES:
            lines.append(f"> （还有 {len(plan_lines) - PLAN_LINES} 行，见 {task}/{tasks.PLAN_NAME}）")
    else:
        lines.append("没有计划文件。")
    lines += ["", "## 经过", "", "| 时间（UTC） | 轮 | 事件 | 说明 |", "| --- | --- | --- | --- |"]
    for event in data.get("events", []):
        lines.append(f"| {event['at'][:19]} | {event.get('round', '')} | {EVENT_TEXT.get(event['what'], event['what'])} | {report.cell(event.get('detail', '')) or '-'} |")
    for old in data.get("rounds", []):
        lines += ["", f"## 第 {old['round']} 轮（已结束）", ""]
        lines.append(f"- 计划批准：{(old.get('plan') or {}).get('approved_at', '没有')}")
        lines.append(f"- 回写：{PROMOTE_TEXT.get(old['promote']['state'], old['promote']['state'])} 分支 {old.get('branch', '')}")
        lines += [f"- {item['action']} {item['path']}" for item in old["promote"].get("files", [])]
        lines.append(f"- 当时的成果：{old.get('dev', '')}")
        if old.get("plan_file"):
            lines.append(f"- 当时的计划：{old['plan_file']}")
    lines += report.log_section(root, {"session_id": data.get("session_id", ""), "surface": data.get("surface", "vscode"), "created_at": data.get("round_started_at", data["created_at"])})
    return "\n".join(lines) + "\n"


def generate(root: Path, raw_task: str = "") -> Dict[str, Any]:
    if raw_task.strip():
        task = task_ops.resolve(root, raw_task)
    else:
        known = [f"{tasks.TASKS_DIR}/{path.name}" for path in sorted((root / tasks.TASKS_DIR).iterdir())] if (root / tasks.TASKS_DIR).is_dir() else []
        started = [(tasks.read(root, name) or {}).get("updated_at", "") for name in known]
        ranked = sorted((stamp, name) for stamp, name in zip(started, known) if stamp)
        if not ranked:
            raise task_ops.CommandError("还没有开始过的任务。")
        task = ranked[-1][1]
    data = task_ops.read(root, task)
    path = report_path(root, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render(root, task, data)
    path.write_text(text, encoding="utf-8")
    return {"task": task, "report": path.relative_to(root).as_posix(), "status": data["status"], "lines": text.count("\n")}
