"""task-levels.json: schema and loading."""

from __future__ import annotations

from typing import Any, Dict

from core import schema

POLICY_NAME = "task-levels"
COUNTER_NAMES = ("observed_tool_calls", "repository_searches", "subagents_created")

_LEVEL_SCHEMA = {
    "type": "object",
    "required": ["subagents", "execution_budget"],
    "properties": {
        "subagents": {"type": "object", "required": ["allowed"], "properties": {"allowed": {"type": "boolean"}}},
        "execution_budget": {
            "type": "object",
            "required": list(COUNTER_NAMES),
            "properties": {name: {"type": "integer", "minimum": 0} for name in COUNTER_NAMES},
        },
    },
}

POLICY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "levels"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "levels": {
            "type": "object",
            "required": ["1", "2", "3"],
            "properties": {"1": _LEVEL_SCHEMA, "2": _LEVEL_SCHEMA, "3": _LEVEL_SCHEMA},
        },
    },
}


def validate_policy(policy: Dict[str, Any]) -> None:
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
