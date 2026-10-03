"""request hook behavior: a subagent call in L3 needs a dispatch, and the subagent is told where its package is.

  PreToolUse(subagent)   L3: only builder and reviewer, and only with a pending dispatch record. The call uses the record up.
                         Other names are refused by task_level. A subagent session cannot call a subagent.
  SubagentStart          the subagent that was just called is told its request, attempt, assignment path and output folder
  Stop, SubagentStop, UserPromptSubmit   the end checks of an L3 request (verify.py)

The pending records live in request.json (written by `dispatch`). The calls waiting for their SubagentStart live in this
module's state of the session that made the call. Both engines report SubagentStart on that session.
A call the tool refuses after this hook let it pass (a missing required argument) never reaches SubagentStart. The call
stays in the waiting list, so the same role may be called again for that attempt without a new dispatch.
Hook failures are fail-open: hook.py rolls back this module's state changes and carries on.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.context import Context
from core.events import Decision, HookEvent
from core.paths import cli_command, mkdir_command

from . import layout, store, verify

NAME = "request"
ROLES = layout.ROLES
CALLS_KEPT = 8


def dispatch_command(request_id: str, role: str) -> str:
    return f"{cli_command()} dispatch --request {request_id} --role {role}"


def refuse(reason: str) -> Decision:
    return Decision(permission="deny", reason=reason)


def on_subagent_call(event: HookEvent, ctx: Context) -> Optional[Decision]:
    request_id = ctx.state.get("active_request")
    if not request_id or ctx.level != 3:
        return None
    if ctx.state.get("parent_session_id"):
        return refuse("子 agent 不能再调用子 agent。做自己的任务，做完用 handoff submit 交接。")
    role = event.subagent_target.strip().lower()
    if role not in ROLES:
        return None  # task_level refuses every name that is not allowed at L3
    with store.locked(ctx.root, request_id) as data:
        pending = [item for item in data["pending_dispatch"] if item["role"] == role]
        if not pending:
            number = data["attempt"]
            used = number >= 1 and role in data["attempts"][number - 1]["dispatched"]
            if used and any(item["role"] == role and item["attempt"] == number for item in ctx.module_state(NAME).get("calls", [])):
                return None  # the earlier call never started: this is the retry
            if used:
                return refuse(
                    f"第 {number} 轮的 {role} 已经调用过了。每次 dispatch 只对应一次调用。"
                    "要再来一轮，先 `attempt new`，再 dispatch；不够就 `request set-status hitl`。"
                )
            return refuse(
                f"L3 调用 {role} 前必须先 dispatch。先填好 to-{role}/assignment.md，再运行 "
                f"`{dispatch_command(request_id, role)}`，然后再调用 {role}。"
            )
        chosen = pending[0]
        data["pending_dispatch"].remove(chosen)
    calls = ctx.module_state(NAME).setdefault("calls", [])
    calls[:] = [item for item in calls if item["role"] != role]  # a call that never started is replaced by this one
    calls.append({"role": role, "attempt": chosen["attempt"]})
    del calls[:-CALLS_KEPT]
    return None


def start_text(request_id: str, role: str, number: int, target_repos: str = "") -> str:
    base = f"{layout.REQUESTS_DIR}/{request_id}"
    where = (
        f"这个请求改的是目标仓库里的文件，成果路径的第一段是仓库名（{target_repos}），例如 `bdtt_repo/src/a.sql`。"
        if target_repos
        else "位置按将来在仓库里的相对路径。"
    )
    package = f"{base}/handoffs/orchestrator/{layout.attempt_name(number)}/to-{role}"
    outputs = f"{base}/{role}/outputs/{layout.attempt_name(number)}"
    return (
        f"你是请求 {request_id} 第 {number} 轮的 {role}。\n"
        f"第一步：读 {package}/assignment.md 和同目录的 manifest.json，按它们工作。\n"
        f"成果和证据写在 {outputs}/ 下，{where}`handoff submit` 的 --output、--evidence 写相对于该目录的路径，不要写完整路径；先用终端 `{mkdir_command()}` 建好父目录（编辑工具不会建）。\n"
        f"做完用 `{cli_command()} handoff submit --request {request_id} --role {role} ...` 交接。"
    )


def target_repo_names(root: Any, request_id: str) -> str:
    """The names of the target repositories when this request has them, else an empty string. Never raises: this is a hint."""
    try:
        if not store.read_request(root, request_id).get("target_mode"):
            return ""
        from core import targets

        return "、".join(targets.load(root).names())
    except Exception:
        return ""


def on_subagent_start(event: HookEvent, ctx: Context) -> Optional[Decision]:
    request_id = ctx.state.get("active_request")
    role = event.agent_type.strip().lower()
    if not request_id or role not in ROLES:
        return None
    calls = ctx.module_state(NAME).get("calls", [])
    found = next((item for item in calls if item["role"] == role), None)
    if found is None:
        return None
    calls.remove(found)
    return Decision(context=start_text(request_id, role, found["attempt"], target_repo_names(ctx.root, request_id)))


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.event == "PreToolUse" and event.tool_kind == "subagent":
        return on_subagent_call(event, ctx)
    if event.event == "SubagentStart":
        return on_subagent_start(event, ctx)
    if event.event == "Stop":
        return verify.on_stop(event, ctx)
    if event.event == "SubagentStop":
        return verify.on_subagent_stop(event, ctx)
    if event.event == "UserPromptSubmit":
        return verify.on_user_prompt(event, ctx)
    return None
