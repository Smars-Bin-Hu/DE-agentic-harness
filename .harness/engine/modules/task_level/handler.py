"""task_level hook handler. Behavior is the same as the first engine, on real VS Code tool names."""

from __future__ import annotations

import math
import re
from typing import Optional

from core.context import Context
from core.events import Decision, HookEvent

from . import lifecycle
from .policy import POLICY_NAME, validate_policy

NAME = "task_level"
SKILL_NAME = "harness-task-level"
WARN_RATIO = 0.8


def is_policy_control_call(event: HookEvent) -> bool:
    """The agent running the level CLI. It is not counted and never denied."""
    return (
        event.tool_kind == "terminal"
        and "cli.py" in event.command
        and re.search(r"\blevel\b", event.command) is not None
    )


def session_context(ctx: Context, ms: dict) -> Decision:
    task = ms["task"]
    text = (
        "Task Level 策略已启用。"
        f"会话 id：{ctx.state['session_id']}。当前状态：{task['status']}；level：{task['level']}。"
        f"分级和切换 Level 见技能 {SKILL_NAME}。"
        "给出最终完成答复之前，先完成当前任务。"
    )
    return Decision(context=text)


def on_session_event(event: HookEvent, ctx: Context, ms: dict) -> Optional[Decision]:
    if event.event == "UserPromptSubmit":
        if event.from_subagent:
            # A subagent call message, not the user (00 section 2, hard conclusion 5).
            return None
        if ms["task"]["status"] != "active":
            lifecycle.begin_task(ms, "New user request defaults to Level 1.")
    return session_context(ctx, ms)


def on_pre_tool_use(event: HookEvent, ctx: Context, ms: dict, policy: dict) -> Optional[Decision]:
    lifecycle.ensure_active_task(ms, "Tool use before task initialization defaults to Level 1.")
    if is_policy_control_call(event):
        return None
    task = ms["task"]
    level = task["level"]
    level_policy = policy["levels"][str(level)]
    budget = level_policy["execution_budget"]
    counters = ms["counters"]
    if event.tool_kind == "subagent":
        if not level_policy["subagents"]["allowed"]:
            return Decision(
                permission="deny",
                reason=(
                    f"Task Level {level} 不允许创建子 agent。"
                    "请自己完成这件事；如果任务确实需要子 agent，建议用户切换 Level 后重发。"
                ),
            )
        if counters["subagents_created"] >= budget["subagents_created"]:
            return Decision(
                permission="deny",
                reason=(
                    f"Task Level {level} 最多创建 {budget['subagents_created']} 个子 agent，已用完。"
                    "请先完成已有的工作，再决定是否继续。"
                ),
            )
        counters["subagents_created"] += 1
    counters["observed_tool_calls"] += 1
    if event.is_search:
        counters["repository_searches"] += 1
    return None


def on_post_tool_use(event: HookEvent, ctx: Context, ms: dict, policy: dict) -> Optional[Decision]:
    if ms["task"]["status"] != "active":
        return None
    level = ms["task"]["level"]
    budget = policy["levels"][str(level)]["execution_budget"]
    messages = []
    for name in ("repository_searches", "observed_tool_calls"):
        current = ms["counters"][name]
        maximum = budget[name]
        marker = f"level-{level}:{name}"
        if current >= math.ceil(maximum * WARN_RATIO) and marker not in ms["warnings_emitted"]:
            status = "已超过" if current > maximum else "已达到"
            messages.append(
                f"Task Level {level} {status}软预算 {name}：{current}/{maximum}。"
                "请专注完成当前工作；只有范围确实需要更多自主权时才升级。"
            )
            ms["warnings_emitted"].append(marker)
    return Decision(context="\n\n".join(messages)) if messages else None


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    policy = ctx.policy(POLICY_NAME)
    validate_policy(policy)
    ms = lifecycle.ensure_module_state(ctx.state, NAME)
    try:
        if event.event in ("SessionStart", "UserPromptSubmit"):
            return on_session_event(event, ctx, ms)
        if event.event == "PreToolUse":
            return on_pre_tool_use(event, ctx, ms, policy)
        if event.event == "PostToolUse":
            return on_post_tool_use(event, ctx, ms, policy)
        return None
    finally:
        lifecycle.sync_shared_level(ctx.state, ms)
