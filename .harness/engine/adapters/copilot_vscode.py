"""VS Code agent mode. Two engines send hook payloads here, so this adapter reads both.

legacy  The Copilot Chat engine, recorded in B1 (2026-09-30). Fixtures: eval/fixtures/hooks/vscode/.
        snake_case, tool names like `run_in_terminal`, output wrapped in `hookSpecificOutput`.
cli     The Copilot SDK engine (`@github/copilot`), recorded 2026-10-01. Fixtures: eval/fixtures/hooks/copilot-sdk/.
        Tool names like `Bash`, results in `tool_result`, SubagentStart is camelCase with no event name,
        a subagent runs in its own session, output is plain top-level keys.

Both report to the same surface (`vscode`), so one state file serves a session whichever engine it runs on.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.events import EVENT_NAMES, Decision, HookEvent

from . import common

SURFACE = "vscode"

# Tool names only the SDK engine uses. The tools a subagent runs there still carry the legacy names.
_CLI_TOOLS = ("Bash", "Read", "Write", "Edit", "Grep", "Glob", "Agent", "search_code_subagent")


def event_name(payload: Dict[str, Any]) -> Any:
    name = payload.get("hook_event_name")
    if name is None and "sessionId" in payload and "agentName" in payload:
        return "SubagentStart"  # the SDK engine sends this one without an event name
    return name


def matches(payload: Dict[str, Any]) -> bool:
    return event_name(payload) in EVENT_NAMES


def engine(payload: Dict[str, Any]) -> str:
    """`cli`, `legacy`, or `unknown` when the payload has no sign of either (e.g. a subagent's `file_search`)."""
    transcript = str(payload.get("transcript_path") or "")
    if (
        "tool_result" in payload
        or "sessionId" in payload
        or "stop_reason" in payload
        or "agent_name" in payload
        or payload.get("tool_name") in _CLI_TOOLS
        or "session-state" in transcript
    ):
        return "cli"
    if "tool_use_id" in payload or "tool_response" in payload or transcript:
        return "legacy"
    return "unknown"


def _result_text(payload: Dict[str, Any]) -> str:
    result = payload.get("tool_result")
    if isinstance(result, dict):
        return common.text(result.get("text_result_for_llm"))
    return common.text(payload.get("tool_response") if "tool_response" in payload else result)


def parse(payload: Dict[str, Any]) -> HookEvent:
    event = common.build_event(
        SURFACE,
        event_name(payload),
        payload,
        payload.get("session_id") or payload.get("sessionId"),
        payload.get("tool_name"),
        payload.get("tool_input"),
    )
    event.cwd = common.text(payload.get("cwd"))
    event.timestamp = common.text(payload.get("timestamp"))
    event.prompt = common.text(payload.get("prompt"))
    event.tool_use_id = common.text(payload.get("tool_use_id"))
    event.tool_response = _result_text(payload)
    event.agent_id = common.text(payload.get("agent_id"))
    event.agent_type = common.text(payload.get("agent_type") or payload.get("agentName"))
    event.stop_hook_active = bool(payload.get("stop_hook_active"))
    return event


def render(event: HookEvent, decision: Optional[Decision]) -> Dict[str, Any]:
    if decision is None or decision.is_empty():
        return {}
    kind = engine(event.raw)
    if event.event in ("UserPromptSubmit", "SessionStart"):
        # The top-level key reaches the model on both engines (B1 R9b; SDK probe 2026-10-01). The nested one only on legacy.
        return common.render_top_level(event, decision)
    if kind == "cli":
        return common.render_top_level(event, decision)
    if kind == "legacy":
        return common.render_nested(event, decision)
    # Unknown engine: each engine reads the keys it knows and ignores the other format.
    return {**common.render_nested(event, decision), **common.render_top_level(event, decision)}
