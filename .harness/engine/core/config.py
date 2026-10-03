"""Policy loading. A policy is .harness/policies/<name>.json; <name>.override.json is merged on top (one layer).

Merge rules: objects merge key by key; anything else in the override replaces the default value (an array is replaced
as a whole); `"<key>+": [...]` appends to the default array `<key>`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .paths import policies_dir

OVERRIDE_SUFFIX = ".override.json"
APPEND_MARK = "+"


class OverrideError(ValueError):
    """The override cannot be merged onto the default (for example `+` on something that is not an array)."""


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def is_append_key(key: str) -> bool:
    return len(key) > 1 and key.endswith(APPEND_MARK)


def deep_merge(base: Any, override: Any, path: str = "") -> Any:
    """The override on top of the base. Neither argument is changed."""
    if not isinstance(override, dict):
        return override
    merged: Dict[str, Any] = dict(base) if isinstance(base, dict) else {}
    plain = [(key, value) for key, value in override.items() if not is_append_key(key)]
    appended = [(key[: -len(APPEND_MARK)], value) for key, value in override.items() if is_append_key(key)]
    for key, value in plain:
        merged[key] = deep_merge(merged[key], value, f"{path}{key}.") if key in merged else deep_merge({}, value, f"{path}{key}.")
    for key, value in appended:
        where = f"{path}{key}"
        current = merged.get(key, [])
        if not isinstance(value, list) or not isinstance(current, list):
            raise OverrideError(f"'{where}{APPEND_MARK}' needs an array on both sides (the default and the override)")
        merged[key] = current + value
    return merged


def changes(base: Any, override: Any, path: str = "") -> List[Tuple[str, str, int]]:
    """Where the override touches the base: (dotted path, how, size). `how` is replaced, appended or added.

    `size` is the length of the array that was replaced or appended to, 0 for anything else.
    """
    found: List[Tuple[str, str, int]] = []
    if not isinstance(override, dict):
        return found
    base = base if isinstance(base, dict) else {}
    for key, value in override.items():
        if is_append_key(key):
            name = key[: -len(APPEND_MARK)]
            found.append((path + name, "appended", len(value) if isinstance(value, list) else 0))
        elif key not in base:
            found.append((path + key, "added", 0))
        elif isinstance(base[key], dict) and isinstance(value, dict):
            found += changes(base[key], value, f"{path}{key}.")
        else:
            found.append((path + key, "replaced", len(base[key]) if isinstance(base[key], list) else 0))
    return found


def override_path(root: Path, name: str) -> Path:
    return policies_dir(root) / f"{name}{OVERRIDE_SUFFIX}"


def load_policy(root: Path, name: str) -> Dict[str, Any]:
    base = read_json(policies_dir(root) / f"{name}.json")
    path = override_path(root, name)
    if path.exists():
        return deep_merge(base, read_json(path))
    return base
