"""L2 review: what the verifier said, whether it came after the last edit, and when Stop must ask for one."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from core.events import Decision, HookEvent

from . import levelstate, rules
from .policy import level_policy, verification, verifier_name, verifier_on

EDIT_KINDS = ("edit", "create")
_VERDICT = re.compile(r"^VERDICT\s*[:：]\s*(PASS|FAIL)\b", re.IGNORECASE)


def parse_verdict(response: str) -> str:
    """`PASS`, `FAIL`, or `unknown`. Reads the first non-empty line; markdown marks around it are ignored."""
    for line in response.splitlines():
        line = line.strip().strip("*#>`_ ")
        if line:
            found = _VERDICT.match(line)
            return found.group(1).upper() if found else "unknown"
    return "unknown"


def is_verifier_call(event: HookEvent, policy: Dict[str, Any]) -> bool:
    if event.tool_kind != "subagent":
        return False
    names = {
        body["verification"]["agent"].lower()
        for body in policy["levels"].values()
        if body["verification"].get("agent") and body["verification"]["mode"] == "verifier"
    }
    return event.subagent_target.strip().lower() in names


def record_post_tool(event: HookEvent, ms: Dict[str, Any], policy: Dict[str, Any]) -> None:
    """PostToolUse: the call has happened. Note edits, and the verdict of a finished verifier call."""
    seq = levelstate.next_seq(ms)
    if event.tool_kind in EDIT_KINDS:
        ms["prompt"]["edits"] += 1
        ms["prompt"]["last_edit_seq"] = seq
    elif is_verifier_call(event, policy):
        ms["reviews"].append({"verdict": parse_verdict(event.tool_response), "seq": seq})


def review_reason(ms: Dict[str, Any], need: Dict[str, Any]) -> str:
    """Why this prompt needs a review, in words: edits, or many tool calls."""
    parts = []
    if ms["prompt"]["edits"]:
        parts.append(f"改了文件（{ms['prompt']['edits']} 次编辑）")
    if need["tool_calls_reached"]:
        parts.append(f"工具调用已达 {ms['counters']['observed_tool_calls']} 次")
    return "、".join(parts)


def needs_review(ms: Dict[str, Any], policy: Dict[str, Any], level: int) -> Optional[Dict[str, Any]]:
    """None if this prompt needs no review, otherwise the facts behind the need."""
    rule = verification(policy, level)
    if not verifier_on(policy, level, ms["prompt"]["verify"]):
        return None
    when = rule.get("require_when", {})
    edited = bool(when.get("edits")) and ms["prompt"]["edits"] > 0
    minimum = when.get("min_tool_calls")
    heavy = minimum is not None and ms["counters"]["observed_tool_calls"] >= minimum
    if not (edited or heavy):
        return None
    return {"edited": edited, "tool_calls_reached": heavy}


def on_stop(event: HookEvent, ms: Dict[str, Any], policy: Dict[str, Any], level: int) -> Optional[Decision]:
    """Block the stop once if this prompt needs a review and has none after the last edit. Nothing when the verifier is off."""
    if event.stop_hook_active:
        return None
    need = needs_review(ms, policy, level)
    if need is None:
        return None
    reviews = ms["reviews"]
    if reviews and reviews[-1]["seq"] > ms["prompt"]["last_edit_seq"]:
        # Reviewed after the last edit. A FAIL here is for the agent to hand to the user (L2-c), so do not block.
        return None
    maximum = level_policy(policy, level)["subagents"].get("max_per_prompt")
    if maximum is not None and ms["counters"]["subagents_created"] >= maximum:
        return None  # the verifier is used up: the agent reports what is left
    agent = verification(policy, level).get("agent", "verifier")
    return Decision(block=True, reason=rules.review_required(policy, level, agent, review_reason(ms, need), bool(reviews)))
