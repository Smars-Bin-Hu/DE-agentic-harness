"""`cli check`: does a request folder agree with itself? Reports every problem; changes nothing.

Checked: the folder layout, request.json against its schema, every dispatched package (manifest schema, file hashes,
assignment hash), every handoff (schema, summary size, listed files exist, agrees with request.json), the brief
(file, hash, snapshot), and the conclusion. A request that is still running is fine; `require_conclusion` is for the end.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core import config

from . import layout, ops, store
from .layout import CommandError
from .policy import POLICY_NAME

BASE_DIRS = ("orchestrator", "builder/outputs", "reviewer/outputs", "handoffs/orchestrator/init-inputs", "handoffs/builder", "handoffs/reviewer")


def run(root: Path, request_id: str, require_conclusion: bool = False) -> Dict[str, Any]:
    problems: List[str] = []
    directory = layout.request_dir(root, request_id)
    try:
        data = store.read_request(root, request_id)
    except CommandError:
        raise
    except Exception as error:
        return {"ok": False, "concluded": False, "problems": [f"request.json 读不了或不合格：{error}"]}
    if data["request_id"] != request_id:
        problems.append(f"request.json 里的 request_id 是 {data['request_id']}，和目录名 {request_id} 不一致。")
    rules = config.load_policy(root, POLICY_NAME)
    for sub in BASE_DIRS:
        if not (directory / sub).is_dir():
            problems.append(f"缺目录：{sub}")
    check_brief(root, directory, data, problems)
    check_targets(root, data, problems)
    if len(data["attempts"]) != data["attempt"]:
        problems.append(f"request.json 的 attempt 是 {data['attempt']}，但记录了 {len(data['attempts'])} 轮。")
    for attempt in data["attempts"]:
        number = attempt["n"]
        for role in layout.ROLES:
            check_package(root, directory, number, role, role in attempt["dispatched"], problems)
            check_handoff(root, directory, number, role, attempt["handoffs"].get(role), rules, problems)
        if "reviewer" in attempt["dispatched"] and "builder" not in attempt["dispatched"]:
            problems.append(f"第 {number} 轮派发了 reviewer，却没有派发 builder。")
    concluded = data["status"] != "open"
    if data["status"] == "accepted" and not data["status_reason"]:
        last = data["attempts"][-1]["handoffs"].get("reviewer") if data["attempts"] else None
        if last != "passed":
            problems.append("状态是 accepted，但最后一轮 reviewer 不是 passed，也没有写 reason。")
    if data["status"] in ("hitl", "abandoned") and not data["status_reason"]:
        problems.append(f"状态是 {data['status']}，但没有写 reason。")
    if require_conclusion and not concluded:
        problems.append("请求还没有结论。用 `request set-status accepted|hitl|abandoned` 结束它。")
    return {"ok": not problems, "request_id": request_id, "status": data["status"], "concluded": concluded, "problems": problems}


def check_targets(root: Path, data: Dict[str, Any], problems: List[str]) -> None:
    from core import targets

    if data.get("branch") and not targets.valid_branch(data["branch"]):
        problems.append(f"分支名 `{data['branch']}` 不合法（要 feature/ 加字母、数字、下划线）。")
    if data.get("task") and not (root / data["task"]).is_dir():
        problems.append(f"任务目录 {data['task']} 不存在。")
    if not data.get("target_mode"):
        return
    try:
        known = set(targets.load(root).names())
    except Exception as error:
        problems.append(f"目标仓库的配置读不了：{error}")
        return
    for name in data.get("targets", {}):
        if name not in known:
            problems.append(f"请求用过仓库 {name}，但 target 配置里现在没有它。")


def check_brief(root: Path, directory: Path, data: Dict[str, Any], problems: List[str]) -> None:
    version = data["brief"]["version"]
    if not version:
        return
    live = layout.brief_file(directory)
    if not live.is_file():
        problems.append("request.json 记录了 brief，但 knowledge-brief.md 不存在。")
    elif store.sha256_file(live) != data["brief"]["sha256"]:
        problems.append("knowledge-brief.md 被直接改过（和 request.json 的 sha256 不一致）。用 `brief set` 提交。")
    for number in range(1, version + 1):
        if not layout.brief_snapshot(directory, number).is_file():
            problems.append(f"缺 brief 快照 v{number:03d}。")


def check_package(root: Path, directory: Path, number: int, role: str, dispatched: bool, problems: List[str]) -> None:
    package = layout.package_dir(directory, number, role)
    manifest_path = package / "manifest.json"
    label = f"{layout.attempt_name(number)}/to-{role}"
    if not dispatched:
        if manifest_path.exists():
            problems.append(f"{label} 有 manifest.json，但 request.json 没有记录派发。")
        return
    if not manifest_path.is_file():
        problems.append(f"{label} 已派发，但缺 manifest.json。")
        return
    try:
        manifest = ops.store_json(manifest_path)
        store.validate(root, "manifest", manifest, f"{label}/manifest.json")
    except Exception as error:
        problems.append(f"{label}/manifest.json 不合格：{error}")
        return
    if manifest["request_id"] != directory.name or manifest["attempt"] != number or manifest["role"] != role:
        problems.append(f"{label}/manifest.json 的 request_id、attempt 或 role 和位置不一致。")
    assignment = package / manifest["assignment"]["path"]
    if not assignment.is_file() or store.sha256_file(assignment) != manifest["assignment"]["sha256"]:
        problems.append(f"{label}/assignment.md 在派发之后被改动，或不存在。")
    for item in manifest["files"]:
        file = package / item["path"]
        if not file.is_file():
            problems.append(f"{label} 缺文件 {item['path']}。")
        elif store.sha256_file(file) != item["sha256"]:
            problems.append(f"{label}/{item['path']} 在派发之后被改动。")


def check_handoff(root: Path, directory: Path, number: int, role: str, recorded: Any, rules: Dict[str, Any], problems: List[str]) -> None:
    path = layout.handoff_file(directory, number, role)
    label = f"handoffs/{role}/{layout.attempt_name(number)}/handoff.json"
    if not path.exists():
        if recorded:
            problems.append(f"request.json 记录了 {role} 第 {number} 轮的 handoff，但文件不存在。")
        return
    try:
        handoff = ops.store_json(path)
        store.validate(root, "handoff", handoff, label)
    except Exception as error:
        problems.append(f"{label} 不合格：{error}")
        return
    if recorded != handoff["status"]:
        problems.append(f"{label} 的 status 是 {handoff['status']}，request.json 记录的是 {recorded}。")
    if handoff["request_id"] != directory.name or handoff["attempt"] != number or handoff["role"] != role:
        problems.append(f"{label} 的 request_id、attempt 或 role 和位置不一致。")
    lines = [line for line in handoff["summary"].splitlines() if line.strip()]
    if len(lines) > rules["handoff"]["summary_max_lines"]:
        problems.append(f"{label} 的 summary 超过 {rules['handoff']['summary_max_lines']} 行。")
    base = layout.outputs_dir(directory, number, role)
    for item in handoff["outputs"] + handoff["evidence"]:
        if not (base / item).is_file():
            problems.append(f"{label} 列出的 {item} 不存在。")
    if handoff["status"] in ("failed", "blocked") and not handoff["blockers"]:
        problems.append(f"{label} 的 status 是 {handoff['status']}，但没有 blockers。")
