"""Copilot CLI. NOT VERIFIED: written from GitHub Docs, never recorded. Re-check in M6-4.

The CLI sends camelCase fields and may send toolArgs as a JSON string. Output is the top-level
format from the docs. Hook configs are shared with VS Code, so detection is by payload shape.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.events import EVENT_NAMES, Decision, HookEvent

from . import common

SURFACE = "cli"

# CLI config event names (camelCase) -> engine event names.
_EVENT_ALIASES = {
    "sessionStart": "SessionStart",
    "userPromptSubmitted": "UserPromptSubmit",
    "preToolUse": "PreToolUse",
    "postToolUse": "PostToolUse",
    "agentStop": "Stop",
    "subagentStop": "SubagentStop",
}


def _event_name(payload: Dict[str, Any]) -> Any:
    raw = payload.get("hookEventName") or payload.get("hook_event_name") or payload.get("event")
    return _EVENT_ALIASES.get(raw, raw)


def matches(payload: Dict[str, Any]) -> bool:
    # The VS Code adapter is asked first. This one takes camelCase payloads.
    return any(key in payload for key in ("sessionId", "toolName", "toolArgs", "hookEventName"))


def _first(payload: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return None


def parse(payload: Dict[str, Any]) -> HookEvent:
    event = common.build_event(
        SURFACE,
        _event_name(payload),
        payload,
        _first(payload, "sessionId", "session_id"),
        _first(payload, "toolName", "tool_name"),
        _first(payload, "toolArgs", "tool_input"),
    )
    event.cwd = common.text(_first(payload, "cwd"))
    event.timestamp = common.text(_first(payload, "timestamp"))
    event.prompt = common.text(_first(payload, "prompt"))
    result = _first(payload, "toolResult", "tool_response")
    event.tool_response = common.text(result.get("textResultForLlm") if isinstance(result, dict) else result)
    event.agent_id = common.text(_first(payload, "agentId", "agent_id"))
    event.agent_type = common.text(_first(payload, "agentType", "agent_type"))
    event.stop_hook_active = bool(_first(payload, "stopHookActive", "stop_hook_active"))
    return event


def render(event: HookEvent, decision: Optional[Decision]) -> Dict[str, Any]:
    if decision is None or decision.is_empty():
        return {}
    output: Dict[str, Any] = {}
    if event.event == "PreToolUse" and decision.permission:
        output["permissionDecision"] = decision.permission
        output["permissionDecisionReason"] = decision.reason
    if event.event in ("Stop", "SubagentStop") and decision.block:
        output["decision"] = "block"
        output["reason"] = decision.reason
    if decision.context and event.event not in ("Stop", "SubagentStop"):
        output["additionalContext"] = decision.context
    return output
