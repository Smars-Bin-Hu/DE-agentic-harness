"""The guardrail files every Level must protect. Core knows them so the gate and promote share one floor."""

from __future__ import annotations

from typing import Any, Dict, List

# Without these the gate would not protect the harness itself. They are always guarded, even when a policy or an
# override drops them from guardrail_paths; doctor reports that as an error.
CORE_GUARDRAILS = (
    ".github/hooks/**",
    ".harness/policies/**",
    ".harness/engine/**",
    ".harness/bin/**",  # the short commands: a changed launcher could run anything under the name `harness`
    ".harness/registry.json",
    ".harness/runtime/**",
    ".vscode/settings.json",  # it holds chat.useHooks: an agent that turns it off turns every hook off
)

# What stays closed in admin mode. The session state and the approvals live in the runtime folder: a session that could
# write it could make itself admin or forge a person's approval.
ADMIN_LOCKED = (".harness/runtime/**",)


def listed(policy: Dict[str, Any]) -> List[str]:
    """What the gate policy lists itself (guardrail_paths and extra_guardrail_paths)."""
    return list(policy.get("guardrail_paths", [])) + list(policy.get("extra_guardrail_paths", []))


def guardrail_paths(policy: Dict[str, Any]) -> List[str]:
    """The core guardrails, then the policy's own. The core ones are always there."""
    return list(dict.fromkeys(list(CORE_GUARDRAILS) + listed(policy)))


def admin_locked(policy: Dict[str, Any]) -> List[str]:
    """The guardrails an admin session still cannot write: the core ones, then the policy's own (`admin_locked_paths`)."""
    return list(dict.fromkeys(list(ADMIN_LOCKED) + list(policy.get("admin_locked_paths", []))))


def missing_core(policy: Dict[str, Any]) -> List[str]:
    have = listed(policy)
    return [item for item in CORE_GUARDRAILS if item not in have]
