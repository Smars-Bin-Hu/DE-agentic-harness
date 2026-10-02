"""Deny circuit breaker (M3-4): the same deny, again and again, ends with a plain stop instruction.

A hook can only refuse a call. It cannot stop an agent that keeps retrying. So from the Nth identical deny in one
prompt window, the reason is replaced by an instruction to stop. Applies to every deny: budget, gate, subagent rules.
The count is per session, because a hook cannot tell the main agent from a subagent in the legacy engine.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

from . import config
from .events import Decision, HookEvent
from .logs import log_error

DEFAULT_REPEAT_LIMIT = 3
# The breaker belongs to no module. Its one number lives in gate.json, next to the other deny rules.
POLICY_NAME = "gate"


def repeat_limit(root: Path) -> int:
    """`circuit_breaker.repeat_limit` from gate.json. 0 turns the breaker off. A broken policy keeps the default."""
    try:
        value = config.load_policy(root, POLICY_NAME).get("circuit_breaker", {}).get("repeat_limit", DEFAULT_REPEAT_LIMIT)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else DEFAULT_REPEAT_LIMIT
    except Exception as error:
        log_error(root, "breaker:policy", error)
        return DEFAULT_REPEAT_LIMIT


def reset(state: Dict[str, Any]) -> None:
    state["denials"] = {}


def stop_text(count: int, reason: str, level: int) -> str:
    text = f"同一个拒绝已出现 {count} 次。停止重试，不要换个办法绕过。"
    if level == 3:
        text += "L3 子 agent：提交 `blocked` handoff，写明缺什么。其他情况：告诉用户被什么拦住了。"
    else:
        text += "告诉用户被什么拦住了，等用户决定。"
    return text + f"\n被拒的原因：{reason}"


def apply(root: Path, state: Dict[str, Any], event: HookEvent, decision: Decision, level: int) -> Optional[Dict[str, Any]]:
    """Count a PreToolUse deny. From the limit on, change `decision.reason` in place. Returns the log entry, or None."""
    if event.event != "PreToolUse" or decision.permission != "deny" or not decision.reason:
        return None
    limit = repeat_limit(root)
    key = hashlib.sha256(decision.reason.encode("utf-8")).hexdigest()[:12]
    counts = state.setdefault("denials", {})
    counts[key] = counts.get(key, 0) + 1
    count = counts[key]
    tripped = limit > 0 and count >= limit
    if tripped:
        decision.reason = stop_text(count, decision.reason, level)
    return {"reason_hash": key, "count": count, "tripped": tripped}
