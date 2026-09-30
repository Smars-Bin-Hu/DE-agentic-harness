"""Module registry: .harness/registry.json. Decides which modules get which events."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from . import config, schema
from .events import EVENT_NAMES
from .paths import registry_path

STATUSES = ["experimental", "active", "deprecated", "retired"]

REGISTRY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "engine", "modules"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "engine": {
            "type": "object",
            "required": ["files"],
            "properties": {"files": {"type": "array", "items": {"type": "string"}}},
        },
        "modules": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["status", "enabled", "events", "files"],
                "properties": {
                    "status": {"type": "string", "enum": STATUSES},
                    "enabled": {"type": "boolean"},
                    "events": {"type": "array", "items": {"type": "string", "enum": list(EVENT_NAMES)}},
                    "enforcement": {"type": "array", "items": {"type": "string", "enum": ["S", "C", "H", "V"]}},
                    "surfaces_verified": {"type": "array", "items": {"type": "string"}},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "retire_when": {"type": "string"},
                },
            },
        },
    },
}


def load_registry(root: Path) -> Dict[str, Any]:
    registry = config.read_json(registry_path(root))
    schema.check(registry, REGISTRY_SCHEMA, "registry.json")
    return registry


def modules_for(registry: Dict[str, Any], event_name: str) -> List[str]:
    """Names of enabled, non-retired modules that subscribe to this event, in registry order."""
    return [
        name
        for name, entry in registry["modules"].items()
        if entry["enabled"] and entry["status"] != "retired" and event_name in entry["events"]
    ]
