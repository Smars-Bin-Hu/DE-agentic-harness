"""Shared adapter helpers: tool_kinds.json, tool input parsing, HookEvent construction."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

from core.events import EVENT_NAMES, Decision, HookEvent

_TOOL_KINDS: Optional[Dict[str, Any]] = None
_SEARCH_PATTERN: Optional[Pattern[str]] = None


def tool_kinds() -> Dict[str, Any]:
    global _TOOL_KINDS
    if _TOOL_KINDS is None:
        path = Path(__file__).resolve().parent / "tool_kinds.json"
        with path.open(encoding="utf-8-sig") as handle:
            _TOOL_KINDS = json.load(handle)
    return _TOOL_KINDS


def surface_config(surface: str) -> Dict[str, Any]:
    return tool_kinds()["surfaces"][surface]


def _search_pattern() -> Pattern[str]:
    global _SEARCH_PATTERN
    if _SEARCH_PATTERN is None:
        names = [r"\s+".join(re.escape(part) for part in name.split()) for name in tool_kinds()["terminal_search_commands"]]
        _SEARCH_PATTERN = re.compile(r"(?:^|[;&|]\s*)(?:" + "|".join(names) + r")\b")
    return _SEARCH_PATTERN


def is_terminal_search(command: str) -> bool:
    return bool(_search_pattern().search(command))


def as_dict(value: Any) -> Dict[str, Any]:
    """tool_input is an object in VS Code. Copilot CLI may send it as a JSON string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def build_event(
    surface: str,
    event: str,
    payload: Dict[str, Any],
    session_id: Any,
    tool_name: Any,
    tool_input: Any,
) -> HookEvent:
    """Fill a HookEvent from already-extracted common values. Shared by both runtimes."""
    if event not in EVENT_NAMES:
        raise ValueError(f"Unsupported hook event: {event!r}")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Hook payload does not include a session id")
    config = surface_config(surface)
    name = tool_name if isinstance(tool_name, str) else ""
    arguments = as_dict(tool_input)
    kind = config["tools"].get(name, "other") if name else ""
    command = arguments.get(config["command_key"])
    command = command if isinstance(command, str) else ""
    paths: List[str] = []
    for key in config["path_keys"]:
        value = arguments.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    result = HookEvent(surface=surface, event=event, session_id=session_id, raw=payload)
    result.tool_name = name
    result.tool_kind = kind
    result.command = command
    result.paths = paths
    result.is_search = kind == "search" or (kind == "terminal" and is_terminal_search(command))
    if kind == "subagent":
        target = arguments.get(config["subagent_target_key"])
        prompt = arguments.get(config["subagent_prompt_key"])
        result.subagent_target = target if isinstance(target, str) else ""
        result.subagent_prompt = prompt if isinstance(prompt, str) else ""
    return result


def render_nested(event: HookEvent, decision: Optional[Decision]) -> Dict[str, Any]:
    """VS Code output format: everything inside hookSpecificOutput, with hookEventName (B1, R4b/R9a)."""
    if decision is None or decision.is_empty():
        return {}
    body: Dict[str, Any] = {"hookEventName": event.event}
    if event.event == "PreToolUse" and decision.permission:
        body["permissionDecision"] = decision.permission
        if decision.reason:
            body["permissionDecisionReason"] = decision.reason
    if event.event in ("Stop", "SubagentStop") and decision.block:
        body["decision"] = "block"
        body["reason"] = decision.reason
    if decision.context and event.event not in ("Stop", "SubagentStop"):
        body["additionalContext"] = decision.context
    return {"hookSpecificOutput": body} if len(body) > 1 else {}
