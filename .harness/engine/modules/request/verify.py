"""The L3 end checks (M5-1). They never decide what is right, only that the paperwork is done.

  Stop           the main agent ends while its request is still open and not marked as waiting for a person: block once
  SubagentStop   builder or reviewer ends before it handed off this attempt: block once, with the command to run
  UserPromptSubmit  a real user prompt arrives: the "waiting for a person" mark of the request is cleared

Both blocks happen once: Stop has `stop_hook_active`, SubagentStop is remembered in this module's state. A block makes the
agent carry on, so a missing handoff or conclusion is asked for once, not argued about. `check` still reports what is wrong.
Policy (orchestration.json, `verify`): `main_stop` true or false; `subagent_stop` "block", "log" (only record it) or "off".
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core import config
from core.context import Context
from core.events import Decision, HookEvent
from core.paths import cli_command, utc_now

from . import layout, store
from .policy import POLICY_NAME, validate_policy

NAME = "request"
BLOCKS_KEPT = 16


def rules(ctx: Context) -> Dict[str, Any]:
    policy = config.load_policy(ctx.root, POLICY_NAME)
    validate_policy(policy)  # a broken policy raises: hook.py logs it and the check does not run (fail-open)
    return policy.get("verify", {"main_stop": True, "subagent_stop": "block"})


def open_request(ctx: Context) -> Optional[Dict[str, Any]]:
    """The running request of this session, or None. A request that cannot be read is nobody's business here."""
    request_id = ctx.state.get("active_request")
    if not request_id:
        return None
    try:
        data = store.read_request(ctx.root, request_id)
    except Exception:
        return None
    return data if data["status"] == "open" else None


def stop_text(request_id: str) -> str:
    return (
        f"请求 {request_id} 还没有收尾。二选一：\n"
        f"1. 做完了：`{cli_command()} request set-status --request {request_id} --status <accepted|hitl|abandoned> [--reason \"<原因>\"]`，"
        f"再 `{cli_command()} check --request {request_id} --require-conclusion`。\n"
        f"2. 在等用户（批准 promote、HITL 的提问、要用户决定）：先 `{cli_command()} request wait --request {request_id} --reason \"<等什么>\"`，再结束。"
        "用户的下一条提示到达时，等待标记自动清除。"
    )


def on_stop(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.stop_hook_active or ctx.state.get("parent_session_id"):
        return None  # the second Stop of a block; or a subagent session (SDK), whose end is checked by SubagentStop
    if not rules(ctx).get("main_stop", True):
        return None
    data = open_request(ctx)
    if data is None or data.get("waiting"):
        return None
    return Decision(block=True, reason=stop_text(data["request_id"]), facts={"kind": "request_not_concluded"})


def handoff_text(request_id: str, role: str, number: int) -> str:
    outputs = f"{layout.REQUESTS_DIR}/{request_id}/{role}/outputs/{layout.attempt_name(number)}"
    return (
        f"你是第 {number} 轮的 {role}，还没有交接。运行："
        f"`{cli_command()} handoff submit --request {request_id} --role {role} --status <passed|failed|blocked> --summary \"<几行以内>\" ...`。\n"
        f"成果和证据放在 {outputs}/ 下，`--output`、`--evidence` 写相对于它的路径。做不完就提交 `--status blocked`，用 `--blocker` 写明缺什么。"
    )


def handed_off(ctx: Context, request_id: str, role: str, number: int, recorded: Any) -> bool:
    """The handoff is recorded in request.json and its file is there and passes the schema."""
    if not recorded:
        return False
    try:
        handoff = store.read_json_file(layout.handoff_file(layout.request_dir(ctx.root, request_id), number, role))
        store.validate(ctx.root, "handoff", handoff, "handoff.json")
    except Exception:
        return False
    return True


def on_subagent_stop(event: HookEvent, ctx: Context) -> Optional[Decision]:
    mode = rules(ctx).get("subagent_stop", "block")
    role = event.agent_type.strip().lower()
    if mode == "off" or role not in layout.ROLES:
        return None
    data = open_request(ctx)
    if data is None or data["attempt"] < 1:
        return None
    number = data["attempt"]
    attempt = data["attempts"][number - 1]
    if role not in attempt["dispatched"]:
        return None  # not a dispatched call; the dispatch rule has its say at PreToolUse
    if handed_off(ctx, data["request_id"], role, number, attempt["handoffs"].get(role)):
        return None
    facts = {"kind": "missing_handoff"}
    key = f"{data['request_id']}:{role}:{number}"
    blocked = ctx.module_state(NAME).setdefault("subagent_blocks", [])
    if mode == "log" or key in blocked:
        return Decision(facts=facts)  # recorded, not blocked: `check` and the orchestrator see the gap
    blocked.append(key)
    del blocked[:-BLOCKS_KEPT]
    return Decision(block=True, reason=handoff_text(data["request_id"], role, number), facts=facts)


def on_user_prompt(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.from_subagent or event.continuation:
        return None
    data = open_request(ctx)
    if data is None or not data.get("waiting"):
        return None
    with store.locked(ctx.root, data["request_id"]) as current:
        current.pop("waiting", None)
    return Decision(facts={"kind": "wait_cleared"})


def mark_waiting(data: Dict[str, Any], reason: str) -> None:
    data["waiting"] = {"reason": reason, "at": utc_now()}
