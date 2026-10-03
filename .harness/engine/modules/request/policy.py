"""orchestration.json: attempt limit, brief size, handoff summary size, input count."""

from __future__ import annotations

from typing import Any, Dict

from core import schema

POLICY_NAME = "orchestration"

POLICY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "max_attempts", "brief", "handoff", "inputs"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "max_attempts": {"type": "integer", "minimum": 1},
        "brief": {
            "type": "object",
            "required": ["max_bytes", "max_entries"],
            "properties": {
                "max_bytes": {"type": "integer", "minimum": 1},
                "max_entries": {"type": "integer", "minimum": 1},
            },
        },
        "handoff": {
            "type": "object",
            "required": ["summary_max_lines"],
            "properties": {"summary_max_lines": {"type": "integer", "minimum": 1}},
        },
        "inputs": {"type": "object", "required": ["max_files"], "properties": {"max_files": {"type": "integer", "minimum": 1}}},
        "verify": {
            "type": "object",
            "required": ["main_stop", "subagent_stop"],
            "properties": {"main_stop": {"type": "boolean"}, "subagent_stop": {"type": "string", "enum": ["block", "log", "off"]}},
        },
    },
}


def validate_policy(policy: Dict[str, Any]) -> None:
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
