"""Texts the model sees: the rules injected at the start of a prompt, and the reasons for a deny.

Every number comes from the policy. Nothing here is a fixed budget.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.paths import cli_command

from .policy import level_policy, verification, verifier_name, verifier_on

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


def subagent_rule(body: Dict[str, Any], off: str = "") -> str:
    """`off` is the verifier's name when it is off for this prompt: it is then not allowed."""
    allowed = [name for name in body["subagents"]["allowed"] if name.lower() != off.lower()]
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


def review_rule(policy: Dict[str, Any], level: int, choice: str = "") -> str:
    """L2: whether and when the verifier must be called. Empty for levels that do not use one."""
    rule = verification(policy, level)
    if rule["mode"] != "verifier":
        return ""
    if not verifier_on(policy, level, choice):
        text = "复核：本条提示没有开启 verifier 复核。自己检查交付物，不要调用子 agent。"
        markers = rule.get("enable_markers", [])
        if markers:
            text += f"用户需要独立复核时，会在提示里写 {'、'.join(markers)}。"
        return text
    when = rule.get("require_when", {})
    triggers = []
    if when.get("edits"):
        triggers.append("改了文件")
    if when.get("min_tool_calls") is not None:
        triggers.append(f"工具调用达到 {when['min_tool_calls']} 次")
    text = f"复核：本条提示{'或'.join(triggers)}时，结束前在最后一次修改之后调用 {rule.get('agent', 'verifier')} 复核一次。"
    text += f"简报写三项：用户的原话、交付物、检查项。复核结论是 FAIL 时，修复后再复核一次；第二次仍 FAIL，就把问题交给用户。"
    markers = rule.get("skip_markers", [])
    if markers:
        text += f"用户在提示里写 {'、'.join(markers)} 时跳过复核。"
    return text


PLANNING_TEXT = {
    "none": "不写计划，只读必要的内容，直接完成。",
    "short": "先写一份短计划，再动手。只探索相关区域。",
    "required": "先写计划，再调度。",
}


def planning_rule(body: Dict[str, Any]) -> str:
    return PLANNING_TEXT.get(body.get("planning", ""), "")


def prompt_rules(policy: Dict[str, Any], level: int, ignored_marker: str = "", choice: str = "", session_id: str = "") -> str:
    """Injected on every user prompt (UserPromptSubmit) and at session start."""
    body = level_policy(policy, level)
    lines = [f"Task Level：L{level}（{body['name']}）。"]
    if ignored_marker:
        lines.append(f"L3 请求进行中，开头的 {ignored_marker} 已被忽略。")
    planning = planning_rule(body)
    if planning:
        lines.append(planning)
    for name in ("repository_searches", "observed_tool_calls"):  # searches first: they are the rule that denies
        lines.append(budget_rule(name, body["budget_per_prompt"][name]))
    off = "" if verifier_on(policy, level, choice) else verifier_name(policy, level)
    lines.append(subagent_rule(body, off))
    review = review_rule(policy, level, choice)
    if review:
        lines.append(review)
    lines.append(
        f"只有用户能切换 Level：用户在提示开头写 {marker_hint(policy)}。"
        "你不能自己切换，也不要运行 level set。任务超出当前 Level 时，停下来告诉用户原因并建议切换。"
    )
    lines.append("工具调用被拒绝时，照拒绝理由里的下一步做。")
    if session_id:
        lines.append(
            f"当前会话 id：{session_id}。orchestrator 运行 `request new` 时，--session-id 原样用它。"
            f"skills 和 agent 文件里的命令前缀 `<cli>` 就是 `{cli_command()}`。"
        )
    if level == 2:
        lines.append(
            "用户指定了 `.workspace/current_tasks/<任务>` 并要你产出或修改文件时，先运行 "
            f"`{cli_command()} task start --task <任务目录> --session-id <当前会话 id>` 进入任务模式：先写 PLAN.md 并等用户批准，之后只在任务的 DEV/ 下写。"
            "只是问答、RCA、出方案、不改文件时，不用开任务。目标仓库的文件任何时候都不能直接改。"
        )
    if level < 3:
        # The prompt starts at L1 or L2 for every agent. Without this line an orchestrator reads the rules above and stops.
        lines.append(
            "你是 orchestrator（用户在 agent 下拉里选的）时，上面的 Level 限制不适用于你：你的第一步是运行 `request new`，"
            "会话由此进入 L3。这不算自己切换 Level，不要因为这里写着 L1 或 L2 而停下。其他 agent 不要运行它。"
        )
    return "\n".join(lines)


def admin_rules(locked: List[str], session_id: str) -> str:
    """Injected instead of the Level rules while the session is in admin mode."""
    cli = cli_command()
    return "\n".join([
        "admin 模式：已开（用户在自己的终端批准的）。这个会话用来二开和排查 harness。Task Level 不适用：没有搜索和工具调用预算，Level 标记不起作用。",
        f"可以改 harness 的文件，包括 guardrail 文件。仍然不能改：{'、'.join(f'`{item}`' for item in locked)}（只读）、CLI 生成的文件（报告、request.json 等）、`.git`、目标仓库。",
        "不能调用子 agent，不能开 L3 请求或 L2 任务。批准类命令（approve-plan、approve-promote、recover、approve-command、admin on）只能由用户运行。git 写命令和危险命令的规则不变。",
        f"改了 `.harness/engine/`、策略或 hook 配置后，运行 `{cli} doctor` 和测试，都通过再交给用户。工具调用被拒绝时，照拒绝理由里的下一步做。",
        f"当前会话 id：{session_id}。`<cli>` 就是 `{cli}`。做完后提醒用户运行 `{cli} admin off --session-id {session_id}`。",
    ])


def admin_subagent_denied(target: str, generic: bool) -> str:
    called = GENERIC_AGENT if generic else target
    return f"admin 模式不允许子 agent（你调用的是：{called}）。请自己完成。"


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


def review_required(policy: Dict[str, Any], level: int, agent: str, why: str, reviewed_before: bool) -> str:
    text = f"L{level} 复核：本条提示{why}，但最后一次修改之后还没有调用 {agent} 复核。"
    if reviewed_before:
        text += "上一次复核之后你又改了文件。"
    text += (
        f"请现在调用一次 {agent}（agentName 填 {agent}），简报写三项：用户的原话、交付物（改了哪些文件）、检查项。"
        "FAIL 时修复后再复核一次；第二次仍 FAIL，就把问题交给用户。"
    )
    markers = verification(policy, level).get("skip_markers", [])
    if markers:
        text += f"用户可以在提示里写 {'、'.join(markers)} 跳过复核。"
    return text


def level_set_denied(policy: Dict[str, Any]) -> str:
    return (
        "只有用户能切换 Level。不要运行 level set。"
        f"需要更高或更低的 Level 时，停下来告诉用户原因，请用户在提示开头写 {marker_hint(policy)}。"
    )


def subagent_denied(policy: Dict[str, Any], level: int, target: str, generic: bool, allowed: List[str]) -> str:
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


def verifier_off(policy: Dict[str, Any], level: int, target: str, generic: bool) -> str:
    """A subagent call refused because the only allowed subagent, the verifier, is off for this prompt."""
    called = GENERIC_AGENT if generic else target
    text = f"L{level} 本条提示没有开启 verifier 复核，不能调用子 agent（你调用的是：{called}）。请自己检查交付物。"
    markers = verification(policy, level).get("enable_markers", [])
    if markers:
        text += f"需要独立复核时，停下来告诉用户，请用户在提示里写 {'、'.join(markers)}。"
    return text


def subagent_limit(level: int, maximum: int) -> str:
    return f"L{level} 每条提示最多调用 {maximum} 次子 agent，已用完。请先完成已有的工作，再向用户交代结果。"
