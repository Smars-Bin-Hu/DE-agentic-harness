"""gate.json: schema, validation and the compiled form the handler uses."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Tuple

from core import repo_paths, schema
from core.guardrails import CORE_GUARDRAILS, guardrail_paths, missing_core

POLICY_NAME = "gate"
# Any `.git` folder (in a target repository or anywhere else) in a terminal command, with the spellings Windows treats as the same.
GIT_FOLDER = r"(?<![\w.-])(?:\.git|git~\d+)\.*(?:::\$\w+)?(?:/[^\s\"']*)?(?![\w.-])"
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
        "cli_owned_paths": {"type": "array", "items": {"type": "string"}},
        "l3_write_root": {"type": "string"},
        "terminal": {
            "type": "object",
            "required": ["guardrail_write", "deny", "ask"],
            "properties": {"guardrail_write": _RULES_SCHEMA, "deny": _RULES_SCHEMA, "ask": _RULES_SCHEMA},
        },
        "git": {"type": "object", "properties": {"approval_minutes": {"type": "integer", "minimum": 1}}},
        "circuit_breaker": {
            "type": "object",
            "properties": {"repeat_limit": {"type": "integer", "minimum": 0}},
        },
    },
}


def expand(pattern: str, guard: str) -> str:
    return pattern.replace(COMMAND_PLACEHOLDER, COMMAND_START).replace(GUARD_PLACEHOLDER, guard)


def validate_policy(policy: Dict[str, Any], floor: bool = True) -> None:
    """`floor=False` is for the gate at run time: a missing core guardrail is not fatal there, the gate adds it back."""
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
    patterns = guardrail_paths(policy)
    for core in missing_core(policy) if floor else ():
        raise ValueError(
            f"Invalid {POLICY_NAME}.json: guardrail_paths must keep {core!r} (core guardrails cannot be removed, also not by an override; use 'guardrail_paths+' to add more)"
        )
    if any(not item.strip() for item in patterns + list(policy.get("cli_owned_paths", []))):
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

    def __init__(self, policy: Dict[str, Any], repos: Optional[List[Tuple[str, Path, List[str]]]] = None) -> None:
        """`repos`: (name, path, refused_paths) of each target repository. Without them only the `.git` floor applies."""
        self.paths = guardrail_paths(policy)
        self.path_regexes: List[Tuple[str, Pattern[str]]] = [(item, repo_paths.glob_regex(item)) for item in self.paths]
        guard = repo_paths.command_regex(self.paths).pattern
        self.guard_writes = [
            (re.compile(expand(rule["pattern"], guard), re.IGNORECASE), rule["why"])
            for rule in policy["terminal"]["guardrail_write"]
        ]
        # Files only the CLI writes (request.json, handoff.json...). Same write patterns as for guardrail files.
        self.owned = list(policy.get("cli_owned_paths", []))
        self.owned_regexes: List[Tuple[str, Pattern[str]]] = [(item, repo_paths.glob_regex(item)) for item in self.owned]
        owned_guard = repo_paths.command_regex(self.owned).pattern if self.owned else ""
        self.owned_writes = [
            (re.compile(expand(rule["pattern"], owned_guard), re.IGNORECASE), rule["why"])
            for rule in policy["terminal"]["guardrail_write"]
        ] if self.owned else []
        self.deny = [(re.compile(expand(rule["pattern"], ""), re.IGNORECASE), rule["why"]) for rule in policy["terminal"]["deny"]]
        self.ask = [(re.compile(expand(rule["pattern"], ""), re.IGNORECASE), rule["why"]) for rule in policy["terminal"]["ask"]]
        self.l3_write_root = policy["l3_write_root"]
        # A `.git` folder is never written by an agent (A4); a target repository's refused_paths are not written either.
        self.repos: List[Tuple[str, Path, List[Tuple[str, Pattern[str]]]]] = [
            (name, path, [(item, repo_paths.glob_regex(item)) for item in refused if item.strip() != ".git/**"])
            for name, path, refused in (repos or [])
        ]
        absolute = [
            f"{repo_paths.normal(str(path))}/{item}"
            for _name, path, refused in (repos or []) for item in refused if item.strip() != ".git/**"
        ]
        target_guard = "(?:" + GIT_FOLDER + (("|" + repo_paths.command_regex(absolute).pattern) if absolute else "") + ")"
        self.target_writes = [
            (re.compile(expand(rule["pattern"], target_guard), re.IGNORECASE), rule["why"])
            for rule in policy["terminal"]["guardrail_write"]
        ]
        # The working tree of a target repository is written by promote only (M7-4). A git command is not judged here:
        # git writes have their own rule (approve-command).
        trees = [f"{repo_paths.normal(str(path))}/**" for _name, path, _refused in (repos or [])]
        tree_guard = repo_paths.command_regex(trees).pattern if trees else ""
        self.tree_writes = [
            (re.compile(expand(rule["pattern"], tree_guard), re.IGNORECASE), rule["why"])
            for rule in policy["terminal"]["guardrail_write"] if not rule["pattern"].startswith(COMMAND_PLACEHOLDER + "git")
        ] if trees else []

    def guardrail_match(self, relative: str) -> str:
        """The guardrail pattern a repo-relative path falls under, or an empty string."""
        for pattern, regex in self.path_regexes:
            if regex.match(relative):
                return pattern
        return ""

    def owned_match(self, relative: str) -> str:
        """The `cli_owned_paths` pattern a repo-relative path falls under, or an empty string."""
        for pattern, regex in self.owned_regexes:
            if regex.match(relative):
                return pattern
        return ""

    def request_root(self, request_id: str) -> str:
        return self.l3_write_root.replace(REQUEST_PLACEHOLDER, request_id).strip("/")

    def repo_of(self, absolute: str) -> Optional[Tuple[str, str]]:
        """`(repo name, repo-relative path)` when an absolute path is inside the working tree of a target repository."""
        for name, path, _patterns in self.repos:
            for relative in repo_paths.inside(absolute, path):
                return name, relative
        return None

    def refused_match(self, absolute: str) -> Optional[Tuple[str, str, str]]:
        """`(repo name, repo-relative path, pattern)` when an absolute path falls under a target repository's refused_paths."""
        for name, path, patterns in self.repos:
            for relative in repo_paths.inside(absolute, path):
                for pattern, regex in patterns:
                    if regex.match(relative):
                        return name, relative, pattern
        return None
