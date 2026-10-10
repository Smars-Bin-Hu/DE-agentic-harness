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
    "required": ["schema_version", "version", "engine", "modules"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
        "released": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "copyright": {"type": "string"},
        "contributors": {"type": "array", "items": {"type": "string"}},
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


def harness_version(root: Path) -> str:
    """The harness release, `major.minor.patch`. `registry.json` is its only source."""
    return load_registry(root)["version"]


BANNER = r"""
    __  __
   / / / /___ __________  ___  __________
  / /_/ / __ `/ ___/ __ \/ _ \/ ___/ ___/
 / __  / /_/ / /  / / / /  __(__  |__  )
/_/ /_/\__,_/_/  /_/ /_/\___/____/____/   version {version}
"""


def version_banner(root: Path) -> str:
    """What `harness --version` prints. ASCII only: it has to show on every terminal, whatever its encoding."""
    registry = load_registry(root)
    lines = [BANNER.strip("\n").format(version=registry["version"]), "", "Copilot Agentic Harness"]
    released = registry.get("released", "")
    if released:
        lines.append(f"Released {released}")
    owner = registry.get("copyright", "")
    if owner:
        lines.append(f"Copyright (c) {released[:4]} {owner}".replace("  ", " "))
    others = registry.get("contributors") or []
    if others:
        lines.append("Contributors: " + ", ".join(others))
    return "\n".join(lines)


def modules_for(registry: Dict[str, Any], event_name: str) -> List[str]:
    """Names of enabled, non-retired modules that subscribe to this event, in registry order."""
    return [
        name
        for name, entry in registry["modules"].items()
        if entry["enabled"] and entry["status"] != "retired" and event_name in entry["events"]
    ]
