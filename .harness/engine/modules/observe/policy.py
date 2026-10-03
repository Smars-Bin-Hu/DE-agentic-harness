"""observe.json: how long a recorded text may be, the capture switch, when doctor says the logs are many."""

from __future__ import annotations

from typing import Any, Dict

from core import schema

POLICY_NAME = "observe"

POLICY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "max_text_chars", "capture", "warn_session_files"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "max_text_chars": {"type": "integer", "minimum": 20},
        "capture": {
            "type": "object",
            "required": ["enabled"],
            "properties": {"enabled": {"type": "boolean"}},
        },
        "warn_session_files": {"type": "integer", "minimum": 1},
    },
}

DEFAULTS: Dict[str, Any] = {
    "schema_version": 1,
    "max_text_chars": 300,
    "capture": {"enabled": False},
    "warn_session_files": 500,
}


def validate_policy(policy: Dict[str, Any]) -> None:
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
