"""The record of one hook call, as it goes into the session log (observe module).

Only the facts a person needs to judge a run: what happened, at which Level, who decided, and for a refusal
what it was about. Tool arguments are not recorded, except the paths and the command of a call that was
denied or sent to a person (`target`). A call that went through leaves no trace of what it touched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .events import Decision, HookEvent

# Who decided. `model` is reserved: a hook cannot see what the main model decided.
JUDGES = ("rule", "verifier", "human", "model")
MAX_PATHS = 5


def outcome_of(decision: Decision) -> str:
    return decision.permission or ("block" if decision.block else ("context" if decision.context else "none"))


def deciding_modules(sources: List[Any], decision: Decision) -> List[str]:
    """Names of the modules whose decision is the merged one: the same permission, or a block."""
    names: List[str] = []
    for name, item in sources:
        if item is None or item.is_empty():
            continue
        if (decision.permission and item.permission == decision.permission) or (decision.block and item.block):
            names.append(name)
    return names


def build(
    event: HookEvent,
    decision: Decision,
    *,
    engine: str,
    ran: List[str],
    sources: List[Any],
    facts: Dict[str, Any],
    level: int,
    parent_session_id: Optional[str],
    denial: Optional[Dict[str, Any]],
    admin: bool = False,
) -> Dict[str, Any]:
    outcome = outcome_of(decision)
    record: Dict[str, Any] = {
        "surface": event.surface,
        "engine": engine,
        "event": event.event,
        "session_id": event.session_id,
        "level": level,
        "tool_name": event.tool_name,
        "agent_type": event.agent_type,
        "from_subagent": event.from_subagent,
        "continuation": event.continuation,
        "modules": ran,
        "decision": outcome,
    }
    if event.tool_kind:
        record["tool_kind"] = event.tool_kind
    if admin:
        record["admin"] = True  # the call ran in admin mode: guardrail files were open to it
    if parent_session_id:
        record["parent_session_id"] = parent_session_id
    if outcome in ("deny", "ask", "block"):
        record["judge"] = "human" if outcome == "ask" else "rule"
        record["by"] = deciding_modules(sources, decision)
        record["reason"] = decision.reason
        if event.event == "PreToolUse" and outcome in ("deny", "ask"):
            record["target"] = {"paths": list(event.paths[:MAX_PATHS]), "command": event.command}
    if denial:
        record["denial"] = denial
    for key in ("kind", "judge", "verdict"):
        if facts.get(key):
            record[key] = facts[key]
    if event.event in ("SessionStart", "SubagentStart", "SubagentStop"):
        # Where to look up which model ran: the transcript, and the model name when the engine reports one.
        record["transcript"] = event.raw.get("transcript_path") or event.raw.get("transcriptPath") or ""
        if event.raw.get("model"):
            record["model"] = event.raw["model"]
    return record
