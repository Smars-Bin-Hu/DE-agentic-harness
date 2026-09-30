"""VS Code agent mode. Payloads are snake_case (recorded in B1, see .harness/eval/fixtures/hooks/vscode/)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.events import EVENT_NAMES, Decision, HookEvent

from . import common

SURFACE = "vscode"


def matches(payload: Dict[str, Any]) -> bool:
    return payload.get("hook_event_name") in EVENT_NAMES


def parse(payload: Dict[str, Any]) -> HookEvent:
    event = common.build_event(
        SURFACE,
        payload.get("hook_event_name"),
        payload,
        payload.get("session_id"),
        payload.get("tool_name"),
        payload.get("tool_input"),
    )
    event.cwd = common.text(payload.get("cwd"))
    event.timestamp = common.text(payload.get("timestamp"))
    event.prompt = common.text(payload.get("prompt"))
    event.tool_use_id = common.text(payload.get("tool_use_id"))
    event.tool_response = common.text(payload.get("tool_response"))
    event.agent_id = common.text(payload.get("agent_id"))
    event.agent_type = common.text(payload.get("agent_type"))
    event.stop_hook_active = bool(payload.get("stop_hook_active"))
    return event


def render(event: HookEvent, decision: Optional[Decision]) -> Dict[str, Any]:
    return common.render_nested(event, decision)
