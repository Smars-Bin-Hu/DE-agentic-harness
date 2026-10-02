"""Module state of task_level: per-prompt counters, edits and reviews, and the level change log.

The level itself lives in the shared `state["level"]` (1 or 2, chosen by the user).
This module owns everything else: what the current prompt has used so far.
"""

from __future__ import annotations

from typing import Any, Dict

from core import schema
from core.paths import utc_now

from .policy import COUNTER_NAMES, SWITCHABLE_LEVELS

STATE_VERSION = 4
CHANGE_LOG_MAX = 20

MODULE_STATE_SCHEMA = {
    "type": "object",
    "required": ["version", "seq", "prompt", "counters", "exceeded", "reviews", "level_changes"],
    "properties": {
        "version": {"type": "integer", "enum": [STATE_VERSION]},
        "seq": {"type": "integer", "minimum": 0},
        "prompt": {
            "type": "object",
            "required": ["count", "verify", "edits", "last_edit_seq"],
            "properties": {
                "count": {"type": "integer", "minimum": 0},
                "verify": {"type": "string", "enum": ["", "on", "off"]},
                "edits": {"type": "integer", "minimum": 0},
                "last_edit_seq": {"type": "integer", "minimum": 0},
            },
        },
        "counters": {
            "type": "object",
            "required": list(COUNTER_NAMES),
            "properties": {name: {"type": "integer", "minimum": 0} for name in COUNTER_NAMES},
        },
        "exceeded": {"type": "array", "items": {"type": "string"}},
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["verdict", "seq"],
                "properties": {"verdict": {"type": "string", "enum": ["PASS", "FAIL", "unknown"]}, "seq": {"type": "integer"}},
            },
        },
        "level_changes": {"type": "array"},
    },
}


def new_module_state() -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        # `seq` orders events inside the session: a review only counts if it comes after the last edit.
        "seq": 0,
        "prompt": {
            "count": 0,
            "started_at": None,
            "verify": "",
            "marker": "",
            "head": "",
            "edits": 0,
            "last_edit_seq": 0,
        },
        "counters": {name: 0 for name in COUNTER_NAMES},
        "exceeded": [],
        "reviews": [],
        "level_changes": [],
    }


def ensure_module_state(state: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Create the module state on first use and validate it every time. Raises on corrupt data.

    State of an older version (the first engine, or B4) is dropped. The shared level survives.
    """
    modules = state["modules"]
    current = modules.get(name)
    if not current or current.get("version") != STATE_VERSION:
        modules[name] = new_module_state()
    schema.check(modules[name], MODULE_STATE_SCHEMA, f"{name} state")
    return modules[name]


def begin_prompt(ms: Dict[str, Any], verify: str, marker: str, head: str = "") -> None:
    """A user prompt starts a new budget window. Counters go back to zero."""
    ms["prompt"] = {
        "count": ms["prompt"]["count"] + 1,
        "started_at": utc_now(),
        "verify": verify,
        "marker": marker,
        "head": head,
        "edits": 0,
        "last_edit_seq": 0,
    }
    ms["counters"] = {name: 0 for name in COUNTER_NAMES}
    ms["exceeded"] = []
    ms["reviews"] = []


def next_seq(ms: Dict[str, Any]) -> int:
    ms["seq"] += 1
    return ms["seq"]


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
