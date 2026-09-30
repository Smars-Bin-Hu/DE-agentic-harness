"""Task lifecycle kept from the first engine: begin, set level, complete, counters.

B3 moves this code into modules/ without changing behavior. B4 replaces the lifecycle with
user-chosen levels (/l1, /l2, [L2]) and per-prompt counting.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict

from core import schema
from core.paths import utc_now

from .policy import COUNTER_NAMES

MODULE_STATE_SCHEMA = {
    "type": "object",
    "required": ["task", "counters", "warnings_emitted", "task_history"],
    "properties": {
        "task": {
            "type": "object",
            "required": ["level", "status"],
            "properties": {
                "level": {"type": "integer", "enum": [1, 2, 3]},
                "status": {"type": "string", "enum": ["idle", "active", "completed"]},
            },
        },
        "counters": {
            "type": "object",
            "required": list(COUNTER_NAMES),
            "properties": {name: {"type": "integer", "minimum": 0} for name in COUNTER_NAMES},
        },
        "warnings_emitted": {"type": "array"},
        "task_history": {"type": "array"},
    },
}


def new_module_state() -> Dict[str, Any]:
    return {
        "task": {
            "id": None,
            "level": 1,
            "previous_level": None,
            "reason": "No active task. The next request starts at Level 1.",
            "status": "idle",
            "started_at": None,
            "completed_at": None,
            "updated_at": utc_now(),
            "transitions": [],
        },
        "counters": {name: 0 for name in COUNTER_NAMES},
        "warnings_emitted": [],
        "task_history": [],
    }


def ensure_module_state(state: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Create the module state on first use and validate it every time. Raises on corrupt data."""
    modules = state["modules"]
    if not modules.get(name):
        modules[name] = new_module_state()
    schema.check(modules[name], MODULE_STATE_SCHEMA, f"{name} state")
    return modules[name]


def sync_shared_level(state: Dict[str, Any], ms: Dict[str, Any]) -> None:
    """Mirror the task level into the shared `level` field (only 1 or 2 is valid there)."""
    state["level"] = min(ms["task"]["level"], 2)


def validate_level(level: int, policy: Dict[str, Any]) -> None:
    if str(level) not in policy["levels"]:
        raise ValueError(f"Unknown Task Level: {level}. Expected 1, 2, or 3.")


def archive_current_task(ms: Dict[str, Any], completion_reason: str) -> None:
    task = ms["task"]
    if not task.get("id"):
        return
    archived = copy.deepcopy(task)
    if task["status"] == "active":
        archived["status"] = "completed"
        archived["completed_at"] = utc_now()
        archived["completion_reason"] = completion_reason
    elif not archived.get("completion_reason"):
        archived["completion_reason"] = completion_reason
    ms["task_history"].append(archived)
    ms["task_history"] = ms["task_history"][-10:]


def begin_task(ms: Dict[str, Any], reason: str, replace: bool = False) -> None:
    if ms["task"]["status"] == "active":
        if not replace:
            raise ValueError("An active task already exists; use begin --replace to replace it.")
        archive_current_task(ms, "replaced")
    elif ms["task"].get("id"):
        archive_current_task(ms, "superseded by new user request")
    now = utc_now()
    ms["task"] = {
        "id": f"task-{uuid.uuid4()}",
        "level": 1,
        "previous_level": None,
        "reason": reason,
        "status": "active",
        "started_at": now,
        "completed_at": None,
        "updated_at": now,
        "transitions": [{"type": "begin", "from_level": None, "to_level": 1, "reason": reason, "at": now}],
    }
    ms["counters"] = {name: 0 for name in COUNTER_NAMES}
    ms["warnings_emitted"] = []


def ensure_active_task(ms: Dict[str, Any], reason: str) -> None:
    if ms["task"]["status"] != "active":
        begin_task(ms, reason)


def set_level(ms: Dict[str, Any], level: int, reason: str, policy: Dict[str, Any]) -> None:
    validate_level(level, policy)
    ensure_active_task(ms, "Task was initialized lazily at Level 1.")
    task = ms["task"]
    old_level = task["level"]
    if old_level == level:
        task["reason"] = reason
        return
    task["previous_level"] = old_level
    task["level"] = level
    task["reason"] = reason
    task["transitions"].append(
        {
            "type": "upgrade" if level > old_level else "downgrade",
            "from_level": old_level,
            "to_level": level,
            "reason": reason,
            "at": utc_now(),
        }
    )


def complete_task(ms: Dict[str, Any], reason: str) -> None:
    ensure_active_task(ms, "Task was initialized lazily at Level 1.")
    task = ms["task"]
    now = utc_now()
    task["transitions"].append(
        {"type": "complete", "from_level": task["level"], "to_level": 1, "reason": reason, "at": now}
    )
    task["previous_level"] = task["level"]
    task["level"] = 1
    task["reason"] = reason
    task["status"] = "completed"
    task["completed_at"] = now
    task["updated_at"] = now
