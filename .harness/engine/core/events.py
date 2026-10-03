"""HookEvent (what a hook received) and Decision (what a module wants), independent of the runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

EVENT_NAMES = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PreCompact",
    "SubagentStart",
    "SubagentStop",
    "Stop",
)

PERMISSION_RANK = {"allow": 1, "ask": 2, "deny": 3}


@dataclass
class HookEvent:
    surface: str
    event: str
    session_id: str
    cwd: str = ""
    timestamp: str = ""
    prompt: str = ""
    tool_name: str = ""
    tool_kind: str = ""
    tool_use_id: str = ""
    command: str = ""
    paths: List[str] = field(default_factory=list)
    is_search: bool = False
    subagent_target: str = ""
    subagent_prompt: str = ""
    agent_id: str = ""
    agent_type: str = ""
    tool_response: str = ""
    stop_hook_active: bool = False
    # Set by core, not by the adapter: this UserPromptSubmit is a subagent call message, not the user.
    from_subagent: bool = False
    # Set by core: this UserPromptSubmit is the engine feeding back the reason of a Stop block, not the user (SDK engine).
    continuation: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    permission: Optional[str] = None  # allow | ask | deny (PreToolUse)
    reason: str = ""  # why denied, or why Stop is blocked
    block: bool = False  # Stop / SubagentStop
    context: str = ""  # text for the model (UserPromptSubmit, SessionStart, SubagentStart)
    # Facts for the call log (observe). Not a decision: `merge` ignores them, and a Decision with only facts is empty.
    # Known keys: `kind` (what kind of refusal, e.g. "budget"), `judge` ("verifier"), `verdict` ("PASS", "FAIL", "unknown").
    facts: Dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.permission or self.block or self.context)


def merge(decisions: Iterable[Optional[Decision]]) -> Decision:
    """deny > ask > allow. Contexts join in order. One block is enough to block."""
    items = [item for item in decisions if item is not None and not item.is_empty()]
    merged = Decision()
    ranked = [item.permission for item in items if item.permission in PERMISSION_RANK]
    if ranked:
        merged.permission = max(ranked, key=lambda name: PERMISSION_RANK[name])
    merged.block = any(item.block for item in items)
    reasons = [
        item.reason
        for item in items
        if item.reason and ((item.permission and item.permission == merged.permission) or item.block)
    ]
    merged.reason = "\n".join(reasons)
    merged.context = "\n\n".join(item.context for item in items if item.context)
    return merged
