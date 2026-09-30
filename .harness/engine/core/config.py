"""Policy loading. A policy is .harness/policies/<name>.json; <name>.override.json is merged on top."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .paths import policies_dir


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def deep_merge(base: Any, override: Any) -> Any:
    """Dicts merge key by key. Anything else in the override replaces the base value."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(base[key], value) if key in base else value
        return merged
    return override


def load_policy(root: Path, name: str) -> Dict[str, Any]:
    base = read_json(policies_dir(root) / f"{name}.json")
    override_path = policies_dir(root) / f"{name}.override.json"
    if override_path.exists():
        return deep_merge(base, read_json(override_path))
    return base
