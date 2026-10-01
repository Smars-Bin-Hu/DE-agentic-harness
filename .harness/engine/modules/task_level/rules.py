"""Texts the model sees: the rules injected at the start of a prompt, and the reasons for a deny.

Every number comes from the policy. Nothing here is a fixed budget.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .policy import level_policy

BUDGET_LABELS = {"repository_searches": "搜索", "observed_tool_calls": "工具调用"}
GENERIC_AGENT = "通用子 agent（没有指定 agentName）"


def marker_hint(policy: Dict[str, Any]) -> str:
    """The markers a user can type, as one line, e.g. `/l1`、`[L1]`、`/l2`、`[L2]`."""
    markers: List[str] = []
    for level in sorted(policy["switch_markers"]):
        markers.extend(policy["switch_markers"][level])
    return "、".join(markers)


def upgrade_hint(policy: Dict[str, Any], level: int) -> str:
    """What to tell the user so they can move up one level. Falls back to a plain sentence."""
    markers = policy["switch_markers"].get(str(level + 1))
    if markers:
        return f"用 {markers[0]} 重发"
    return "切换到更高的 Level"


def subagent_rule(body: Dict[str, Any]) -> str:
    allowed = body["subagents"]["allowed"]
    if not allowed:
        return "子 agent：不允许。"
    text = "子 agent：只允许 " + "、".join(allowed)
    maximum = body["subagents"].get("max_per_prompt")
    return text + (f"，每条提示最多 {maximum} 次。" if maximum is not None else "。")


def budget_rule(name: str, budget: Dict[str, Any]) -> str:
    label = BUDGET_LABELS[name]
    if budget["on_exceed"] == "deny":
        return f"{label}最多 {budget['limit']} 次，超过会被拒绝。"
    return f"{label}建议不超过 {budget['limit']} 次，超过不会被拒绝，但会被记录。"


def prompt_rules(policy: Dict[str, Any], level: int, ignored_marker: str = "") -> str:
    """Injected on every user prompt (UserPromptSubmit) and at session start."""
    body = level_policy(policy, level)
    lines = [f"Task Level：L{level}（{body['name']}）。"]
    if ignored_marker:
        lines.append(f"L3 请求进行中，开头的 {ignored_marker} 已被忽略。")
    for name in ("repository_searches", "observed_tool_calls"):  # searches first: they are the rule that denies
        lines.append(budget_rule(name, body["budget_per_prompt"][name]))
    lines.append(subagent_rule(body))
    lines.append(
        f"只有用户能切换 Level：用户在提示开头写 {marker_hint(policy)}。"
        "你不能自己切换，也不要运行 level set。任务超出当前 Level 时，停下来告诉用户原因并建议切换。"
    )
    lines.append("工具调用被拒绝时，照拒绝理由里的下一步做。")
    return "\n".join(lines)


def search_denied(policy: Dict[str, Any], level: int, limit: int) -> str:
    return (
        f"L{level} 探索预算已用完（搜索最多 {limit} 次）。"
        f"根据已读内容直接完成；信息不够就停下来，建议用户{upgrade_hint(policy, level)}。"
    )


def tool_calls_denied(policy: Dict[str, Any], level: int, limit: int) -> str:
    return (
        f"L{level} 的工具调用预算已用完（最多 {limit} 次）。"
        f"根据已有结果直接完成；信息不够就停下来，建议用户{upgrade_hint(policy, level)}。"
    )


def level_set_denied(policy: Dict[str, Any]) -> str:
    return (
        "只有用户能切换 Level。不要运行 level set。"
        f"需要更高或更低的 Level 时，停下来告诉用户原因，请用户在提示开头写 {marker_hint(policy)}。"
    )


def subagent_denied(policy: Dict[str, Any], level: int, target: str, generic: bool) -> str:
    body = level_policy(policy, level)
    allowed = body["subagents"]["allowed"]
    called = GENERIC_AGENT if generic else target
    if not allowed:
        return (
            f"L{level} 不允许子 agent（你调用的是：{called}）。"
            f"请自己完成；确实需要子 agent 时，停下来建议用户{upgrade_hint(policy, level)}。"
        )
    return (
        f"L{level} 只允许这些子 agent：{'、'.join(allowed)}。你调用的是：{called}。"
        "请改用允许的子 agent，或自己完成。"
    )


def subagent_limit(level: int, maximum: int) -> str:
    return f"L{level} 每条提示最多调用 {maximum} 次子 agent，已用完。请先完成已有的工作，再向用户交代结果。"
