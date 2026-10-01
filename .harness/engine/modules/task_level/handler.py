"""task_level hook handler.

  SessionStart / UserPromptSubmit  parse the user's level marker, open a new budget window, inject the rules
  PreToolUse                       count; deny a `level set` call, a subagent that is not allowed, an exhausted budget

Hook failures are fail-open: hook.py rolls back this module's state changes and carries on.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.context import Context
from core.events import Decision, HookEvent

from . import levelstate, markers, rules
from .policy import POLICY_NAME, level_policy, validate_policy

NAME = "task_level"
# SubagentStart reports the built-in subagent as `default`. It has no agentName in PreToolUse. Both are "generic".
GENERIC_AGENT_NAMES = ("", "default")

_LEVEL_SET = re.compile(r"\blevel\s+set\b", re.IGNORECASE)


def is_level_set_call(event: HookEvent) -> bool:
    """The agent running the CLI that changes the level. Only the user may do that."""
    if event.tool_kind != "terminal":
        return False
    command = event.command.replace('"', " ").replace("'", " ")
    return "cli.py" in command and _LEVEL_SET.search(command) is not None


def is_generic_agent(name: str) -> bool:
    return name.strip().lower() in GENERIC_AGENT_NAMES


def on_user_prompt(event: HookEvent, ctx: Context, ms: Dict[str, Any], policy: Dict[str, Any]) -> Optional[Decision]:
    if event.from_subagent:
        # A subagent call message, not the user (00 section 2, hard conclusion 5).
        return None
    switch = markers.parse_switch(event.prompt, policy)
    ignored = ""
    written = switch[1] if switch else ""
    if switch and ctx.state["active_request"]:
        ignored, switch = switch[1], None  # an L3 request is running: markers do nothing
    if switch:
        levelstate.set_level(ctx.state, ms, switch[0], "marker")
    # `head` is the start of the prompt as the hook saw it. It shows whether `/l2` reaches the hook as typed.
    levelstate.begin_prompt(ms, markers.wants_skip_verify(event.prompt, policy), written, event.prompt.strip()[:40])
    return Decision(context=rules.prompt_rules(policy, ctx.level, ignored))


def on_session_start(ctx: Context, policy: Dict[str, Any]) -> Optional[Decision]:
    return Decision(context=rules.prompt_rules(policy, ctx.level))


def deny_subagent(event: HookEvent, ctx: Context, ms: Dict[str, Any], policy: Dict[str, Any]) -> Optional[Decision]:
    level = ctx.level
    subagents = level_policy(policy, level)["subagents"]
    target = event.subagent_target
    generic = is_generic_agent(target)
    allowed = [name.lower() for name in subagents["allowed"]]
    if generic or target.strip().lower() not in allowed:
        return Decision(permission="deny", reason=rules.subagent_denied(policy, level, target, generic))
    # `require_dispatch` (L3) is checked by the request module (M4-4). No L3 request exists before B7.
    maximum = subagents.get("max_per_prompt")
    if maximum is not None and ms["counters"]["subagents_created"] >= maximum:
        return Decision(permission="deny", reason=rules.subagent_limit(level, maximum))
    return None


def deny_budget(event: HookEvent, ctx: Context, ms: Dict[str, Any], policy: Dict[str, Any]) -> Optional[Decision]:
    """The first budget that is used up and set to `deny`. The call has not happened, so nothing is counted."""
    level = ctx.level
    budgets = level_policy(policy, level)["budget_per_prompt"]
    for name in _budgets_for(event):
        budget = budgets[name]
        if budget["on_exceed"] == "deny" and ms["counters"][name] >= budget["limit"]:
            if name == "repository_searches":
                return Decision(permission="deny", reason=rules.search_denied(policy, level, budget["limit"]))
            return Decision(permission="deny", reason=rules.tool_calls_denied(policy, level, budget["limit"]))
    return None


def _budgets_for(event: HookEvent) -> List[str]:
    return ["repository_searches", "observed_tool_calls"] if event.is_search else ["observed_tool_calls"]


def count_call(event: HookEvent, ctx: Context, ms: Dict[str, Any], policy: Dict[str, Any]) -> None:
    budgets = level_policy(policy, ctx.level)["budget_per_prompt"]
    counters = ms["counters"]
    if event.tool_kind == "subagent":
        counters["subagents_created"] += 1
    for name in _budgets_for(event):
        counters[name] += 1
        if counters[name] > budgets[name]["limit"] and name not in ms["exceeded"]:
            ms["exceeded"].append(name)  # on_exceed=warn: PostToolUse cannot reach the model, so the record is the warning


def on_pre_tool_use(event: HookEvent, ctx: Context, ms: Dict[str, Any], policy: Dict[str, Any]) -> Optional[Decision]:
    if is_level_set_call(event):
        return Decision(permission="deny", reason=rules.level_set_denied(policy))
    if event.tool_kind == "subagent":
        denied = deny_subagent(event, ctx, ms, policy)
        if denied:
            return denied
    denied = deny_budget(event, ctx, ms, policy)
    if denied:
        return denied
    count_call(event, ctx, ms, policy)
    return None


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    policy = ctx.policy(POLICY_NAME)
    validate_policy(policy)
    ms = levelstate.ensure_module_state(ctx.state, NAME)
    if event.event == "SessionStart":
        return on_session_start(ctx, policy)
    if event.event == "UserPromptSubmit":
        return on_user_prompt(event, ctx, ms, policy)
    if event.event == "PreToolUse":
        return on_pre_tool_use(event, ctx, ms, policy)
    return None
