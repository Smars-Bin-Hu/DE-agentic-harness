"""Module state of task_level: per-prompt counters and the level change log.

The level itself lives in the shared `state["level"]` (1 or 2, chosen by the user).
This module owns everything else: what the current prompt has used so far.
"""

from __future__ import annotations

from typing import Any, Dict

from core import schema
from core.paths import utc_now

from .policy import COUNTER_NAMES, SWITCHABLE_LEVELS

STATE_VERSION = 2
CHANGE_LOG_MAX = 20

MODULE_STATE_SCHEMA = {
    "type": "object",
    "required": ["version", "prompt", "counters", "exceeded", "level_changes"],
    "properties": {
        "version": {"type": "integer", "enum": [STATE_VERSION]},
        "prompt": {
            "type": "object",
            "required": ["count", "skip_verify"],
            "properties": {
                "count": {"type": "integer", "minimum": 0},
                "skip_verify": {"type": "boolean"},
            },
        },
        "counters": {
            "type": "object",
            "required": list(COUNTER_NAMES),
            "properties": {name: {"type": "integer", "minimum": 0} for name in COUNTER_NAMES},
        },
        "exceeded": {"type": "array", "items": {"type": "string"}},
        "level_changes": {"type": "array"},
    },
}


def new_module_state() -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "prompt": {"count": 0, "started_at": None, "skip_verify": False, "marker": "", "head": ""},
        "counters": {name: 0 for name in COUNTER_NAMES},
        "exceeded": [],
        "level_changes": [],
    }


def ensure_module_state(state: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Create the module state on first use and validate it every time. Raises on corrupt data.

    State written by the first engine (task lifecycle, no `version`) is dropped. The shared level survives.
    """
    modules = state["modules"]
    current = modules.get(name)
    if not current or "version" not in current:
        modules[name] = new_module_state()
    schema.check(modules[name], MODULE_STATE_SCHEMA, f"{name} state")
    return modules[name]


def begin_prompt(ms: Dict[str, Any], skip_verify: bool, marker: str, head: str = "") -> None:
    """A user prompt starts a new budget window. Counters go back to zero."""
    ms["prompt"] = {
        "count": ms["prompt"]["count"] + 1,
        "started_at": utc_now(),
        "skip_verify": skip_verify,
        "marker": marker,
        "head": head,
    }
    ms["counters"] = {name: 0 for name in COUNTER_NAMES}
    ms["exceeded"] = []


def set_level(state: Dict[str, Any], ms: Dict[str, Any], level: int, source: str) -> bool:
    """Change the shared level. Returns True if it changed. `source` is `marker` or `cli`."""
    if level not in SWITCHABLE_LEVELS:
        raise ValueError(f"Unknown level: {level}. A user can choose 1 or 2. Level 3 starts from an L3 request.")
    old = state["level"]
    if old == level:
        return False
    state["level"] = level
    ms["level_changes"].append({"from_level": old, "to_level": level, "source": source, "at": utc_now()})
    del ms["level_changes"][:-CHANGE_LOG_MAX]
    return True
