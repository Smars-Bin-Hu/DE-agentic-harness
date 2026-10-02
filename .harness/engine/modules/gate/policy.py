"""gate.json: schema, validation and the compiled form the handler uses."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Pattern, Tuple

from core import schema

from . import repo_paths

POLICY_NAME = "gate"
# Without these the gate would not protect the harness itself. An override must keep them (doctor reports it).
CORE_GUARDRAILS = (
    ".github/hooks/**",
    ".harness/policies/**",
    ".harness/engine/**",
    ".harness/registry.json",
    ".harness/runtime/**",
    ".vscode/settings.json",  # it holds chat.useHooks: an agent that turns it off turns every hook off
)
REQUEST_PLACEHOLDER = "{request_id}"
GUARD_PLACEHOLDER = "{guard}"
# Where a command can start: the beginning, or after `;`, `&`, `|`, `(`, a new line. An optional `sudo` may lead.
# Patterns use it so that `grep "rm -rf" file` (rm inside an argument) does not look like a command.
COMMAND_PLACEHOLDER = "{cmd}"
COMMAND_START = r"(?:^|[;&|(\n]\s*)(?:sudo\s+)?"

_RULE_SCHEMA = {
    "type": "object",
    "required": ["pattern", "why"],
    "properties": {"pattern": {"type": "string"}, "why": {"type": "string"}},
}
_RULES_SCHEMA = {"type": "array", "items": _RULE_SCHEMA}

POLICY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "guardrail_paths", "l3_write_root", "terminal"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "guardrail_paths": {"type": "array", "items": {"type": "string"}},
        "extra_guardrail_paths": {"type": "array", "items": {"type": "string"}},
        "l3_write_root": {"type": "string"},
        "terminal": {
            "type": "object",
            "required": ["guardrail_write", "deny", "ask"],
            "properties": {"guardrail_write": _RULES_SCHEMA, "deny": _RULES_SCHEMA, "ask": _RULES_SCHEMA},
        },
        "circuit_breaker": {
            "type": "object",
            "properties": {"repeat_limit": {"type": "integer", "minimum": 0}},
        },
    },
}


def expand(pattern: str, guard: str) -> str:
    return pattern.replace(COMMAND_PLACEHOLDER, COMMAND_START).replace(GUARD_PLACEHOLDER, guard)


def guardrail_paths(policy: Dict[str, Any]) -> List[str]:
    return list(policy["guardrail_paths"]) + list(policy.get("extra_guardrail_paths", []))


def validate_policy(policy: Dict[str, Any]) -> None:
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
    patterns = guardrail_paths(policy)
    for core in CORE_GUARDRAILS:
        if core not in patterns:
            raise ValueError(f"Invalid {POLICY_NAME}.json: guardrail_paths must keep {core!r}")
    if any(not item.strip() for item in patterns):
        raise ValueError(f"Invalid {POLICY_NAME}.json: empty guardrail path")
    if REQUEST_PLACEHOLDER not in policy["l3_write_root"]:
        raise ValueError(f"Invalid {POLICY_NAME}.json: l3_write_root must contain {REQUEST_PLACEHOLDER}")
    for group in ("guardrail_write", "deny", "ask"):
        for rule in policy["terminal"][group]:
            if group == "guardrail_write" and GUARD_PLACEHOLDER not in rule["pattern"]:
                raise ValueError(f"Invalid {POLICY_NAME}.json: a guardrail_write pattern must contain {GUARD_PLACEHOLDER}")
            try:
                re.compile(expand(rule["pattern"], "x"))
            except re.error as error:
                raise ValueError(f"Invalid {POLICY_NAME}.json: bad pattern {rule['pattern']!r}: {error}") from error


class Compiled:
    """The policy with its patterns compiled. Built once per hook call."""

    def __init__(self, policy: Dict[str, Any]) -> None:
        self.paths = guardrail_paths(policy)
        self.path_regexes: List[Tuple[str, Pattern[str]]] = [(item, repo_paths.glob_regex(item)) for item in self.paths]
        guard = repo_paths.command_regex(self.paths).pattern
        self.guard_writes = [
            (re.compile(expand(rule["pattern"], guard), re.IGNORECASE), rule["why"])
            for rule in policy["terminal"]["guardrail_write"]
        ]
        self.deny = [(re.compile(expand(rule["pattern"], ""), re.IGNORECASE), rule["why"]) for rule in policy["terminal"]["deny"]]
        self.ask = [(re.compile(expand(rule["pattern"], ""), re.IGNORECASE), rule["why"]) for rule in policy["terminal"]["ask"]]
        self.l3_write_root = policy["l3_write_root"]

    def guardrail_match(self, relative: str) -> str:
        """The guardrail pattern a repo-relative path falls under, or an empty string."""
        for pattern, regex in self.path_regexes:
            if regex.match(relative):
                return pattern
        return ""

    def request_root(self, request_id: str) -> str:
        return self.l3_write_root.replace(REQUEST_PLACEHOLDER, request_id).strip("/")
