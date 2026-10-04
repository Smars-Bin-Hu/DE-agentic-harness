"""The plan of an L3 request needs a person's approval before the first attempt (M7-1).

The orchestrator writes `orchestrator/plan.md` and stops. The person reads the file in the editor and runs
`request approve-plan` in a terminal: the code typed there is bound to the sha256 of plan.md. `attempt new` refuses while
the plan has no approval, or was changed after it. A rework attempt with an unchanged plan needs no new approval.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core import approval
from core.paths import cli_command, utc_now

from . import layout, ops, store
from .layout import CommandError

PLAN_NAME = "orchestrator/plan.md"


def plan_path(root: Path, request_id: str) -> Path:
    return layout.request_dir(root, request_id) / PLAN_NAME


def approve_command(request_id: str) -> str:
    return f"{cli_command()} request approve-plan --request {request_id}"


def digest(root: Path, request_id: str) -> str:
    """sha256 of plan.md, or an empty string when it is missing."""
    path = plan_path(root, request_id)
    return store.sha256_file(path) if path.is_file() else ""


def approved(root: Path, request_id: str, data: Dict[str, Any]) -> bool:
    current = digest(root, request_id)
    return bool(current) and (data.get("plan") or {}).get("approved_sha256") == current


def require_ready(root: Path, request_id: str) -> Path:
    """The plan file, when it is written. Raises when it is missing or still holds the placeholder."""
    path = plan_path(root, request_id)
    shown = layout.inside(root, path) or str(path)
    if not path.is_file():
        raise CommandError(f"还没有计划文件 {shown}。先让 agent 写好计划。")
    if ops.PLACEHOLDER in path.read_text(encoding="utf-8"):
        raise CommandError(f"{shown} 里还有“{ops.PLACEHOLDER}”，计划还没写完。先让 agent 写好计划。")
    return path


def require_approved(root: Path, request_id: str, data: Dict[str, Any]) -> None:
    """`attempt new` calls this. The message tells the orchestrator how to hand the plan to the person."""
    path = require_ready(root, request_id)
    if approved(root, request_id, data):
        return
    shown = layout.inside(root, path) or str(path)
    changed = "计划在批准之后改过，要重新批准。" if (data.get("plan") or {}).get("approved_sha256") else "计划还没有经用户批准。"
    raise CommandError(
        f"{changed}现在停下来：用两三句话告诉用户计划的要点，给出链接 [plan.md]({shown})（让用户在编辑器里打开看），"
        f"运行 `{cli_command()} request wait --request {request_id} --reason \"等用户批准计划\"`，"
        f"请用户在自己的终端运行 `{approve_command(request_id)}` 并输入确认码。你不能自己运行它。用户说批准好了，再 `attempt new`。"
    )


def waiting_request(root: Path) -> str:
    """The one open request whose plan is written and not approved. Raises when there is none or several."""
    waiting = []
    for item in ops.list_requests(root, "open")["requests"]:
        if not item["plan_approved"] and item["plan_ready"]:
            waiting.append(item["request_id"])
    if not waiting:
        raise CommandError("没有等待批准计划的请求。先让 agent 写好 orchestrator/plan.md；或用 `request list` 看所有请求。")
    if len(waiting) > 1:
        raise CommandError("有好几个请求在等批准计划：" + "、".join(waiting) + "。用 --request 指定一个。")
    return waiting[0]


def approve(
    root: Path,
    request_id: str = "",
    reader: Optional[Callable[[str], str]] = None,
    interactive: Optional[bool] = None,
    out: Any = None,
) -> Dict[str, Any]:
    """The person approves plan.md as it is now. Terminal only; the screen names the file, it does not print it."""
    try:
        approval.require_person("approve-plan", interactive)
    except approval.Refused as error:
        raise CommandError(str(error)) from error
    request_id = request_id or waiting_request(root)
    data = store.read_request(root, request_id)
    store.require_open(data)
    path = require_ready(root, request_id)
    current = store.sha256_file(path)
    shown = layout.inside(root, path) or str(path)
    lines = len(path.read_text(encoding="utf-8").splitlines())
    approval.say(
        out,
        f"请求 {request_id}：{data['title']}",
        f"计划在这个文件里（{lines} 行），先在编辑器里打开看：{shown}",
        "批准后 agent 才能开第一轮。计划再改，要重新批准。",
    )
    try:
        approval.ask("确认按这份计划做", current, "没有批准。agent 还不能开工。", reader)
    except approval.Refused as error:
        raise CommandError(str(error)) from error
    with store.locked(root, request_id) as locked:
        store.require_open(locked)
        if digest(root, request_id) != current:
            raise CommandError("你确认的时候计划变了。重新打开文件看一遍，再运行 approve-plan。")
        locked["plan"] = {"approved_sha256": current, "approved_at": utc_now()}
    return {"approved": True, "request_id": request_id, "plan": shown, "next": "告诉 agent 计划已批准，可以 `attempt new` 开工了。"}
