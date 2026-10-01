"""task-levels.json (schema 2): schema, validation and the small helpers that read it."""

from __future__ import annotations

from typing import Any, Dict, List

from core import schema

POLICY_NAME = "task-levels"
# Counters in the module state. The first two have a budget in the policy; the third is capped by `max_per_prompt`.
COUNTER_NAMES = ("observed_tool_calls", "repository_searches", "subagents_created")
BUDGET_NAMES = ("observed_tool_calls", "repository_searches")
# The only levels a user can pick with a marker. Level 3 is entered through an L3 request (B7).
SWITCHABLE_LEVELS = (1, 2)

_BUDGET_SCHEMA = {
    "type": "object",
    "required": ["limit", "on_exceed"],
    "properties": {
        "limit": {"type": "integer", "minimum": 0},
        "on_exceed": {"type": "string", "enum": ["warn", "deny"]},
    },
}

_LEVEL_SCHEMA = {
    "type": "object",
    "required": ["name", "subagents", "budget_per_prompt", "verification"],
    "properties": {
        "name": {"type": "string"},
        "subagents": {
            "type": "object",
            "required": ["allowed"],
            "properties": {
                "allowed": {"type": "array", "items": {"type": "string"}},
                "max_per_prompt": {"type": "integer", "minimum": 0},
                "require_dispatch": {"type": "boolean"},
            },
        },
        "budget_per_prompt": {
            "type": "object",
            "required": list(BUDGET_NAMES),
            "properties": {name: _BUDGET_SCHEMA for name in BUDGET_NAMES},
        },
        "verification": {
            "type": "object",
            "required": ["mode"],
            "properties": {
                "mode": {"type": "string", "enum": ["self", "verifier", "reviewer"]},
                "require_when": {
                    "type": "object",
                    "properties": {
                        "edits": {"type": "boolean"},
                        "min_tool_calls": {"type": ["integer", "null"], "minimum": 0},
                    },
                },
                "skip_markers": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}

POLICY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "switch_markers", "levels"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [2]},
        "switch_markers": {
            "type": "object",
            "required": [str(level) for level in SWITCHABLE_LEVELS],
            "properties": {
                str(level): {"type": "array", "items": {"type": "string"}} for level in SWITCHABLE_LEVELS
            },
        },
        "levels": {
            "type": "object",
            "required": ["1", "2", "3"],
            "properties": {"1": _LEVEL_SCHEMA, "2": _LEVEL_SCHEMA, "3": _LEVEL_SCHEMA},
        },
    },
}


def validate_policy(policy: Dict[str, Any]) -> None:
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
    seen: Dict[str, str] = {}
    for level, markers in policy["switch_markers"].items():
        for marker in markers:
            if not marker.strip():
                raise ValueError(f"Invalid {POLICY_NAME}.json: empty switch marker for level {level}")
            if marker.lower() in seen:
                raise ValueError(f"Invalid {POLICY_NAME}.json: marker {marker!r} is used twice")
            seen[marker.lower()] = level


def level_policy(policy: Dict[str, Any], level: int) -> Dict[str, Any]:
    return policy["levels"][str(level)]


def skip_markers(policy: Dict[str, Any]) -> List[str]:
    """Markers that skip the verifier check for one prompt, from every level that defines them."""
    found: List[str] = []
    for body in policy["levels"].values():
        for marker in body["verification"].get("skip_markers", []):
            if marker not in found:
                found.append(marker)
    return found
