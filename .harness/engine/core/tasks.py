"""An L2 task: where its files live and what its state says. Core knows it so the gate need not import the task module.

A task is a folder under `.workspace/current_tasks/`. The person puts the requirement there (`REQ/`, `REF/`). In task mode
the agent writes `PLAN.md` and, once the person approved it, files under `DEV/`. Everything else in the folder that is not
the person's is the CLI's: `.task/` (state, the main version of fetched files) and the two diff files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

TASKS_DIR = ".workspace/current_tasks"
PLAN_NAME = "PLAN.md"
DEV_NAME = "DEV"
STATE_DIR = ".task"
STATE_NAME = "task.json"
BASE_NAME = "base"
CHANGES_NAME = "CHANGES.diff"
REVIEW_NAME = "PROMOTE-PLAN.diff"


def task_dir(root: Path, task: str) -> Path:
    """`task` is the repository-relative path of the task folder, as the session state keeps it."""
    return root / task


def state_file(root: Path, task: str) -> Path:
    return task_dir(root, task) / STATE_DIR / STATE_NAME


def plan_file(root: Path, task: str) -> Path:
    return task_dir(root, task) / PLAN_NAME


def dev_dir(root: Path, task: str) -> Path:
    return task_dir(root, task) / DEV_NAME


def base_dir(root: Path, task: str) -> Path:
    return task_dir(root, task) / STATE_DIR / BASE_NAME


def read(root: Path, task: str) -> Optional[Dict[str, Any]]:
    """task.json, or None when the task was never started or the file cannot be read."""
    try:
        with state_file(root, task).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def plan_digest(root: Path, task: str) -> str:
    """sha256 of PLAN.md, or an empty string when there is none."""
    try:
        return hashlib.sha256(plan_file(root, task).read_bytes()).hexdigest()
    except OSError:
        return ""


def plan_approved(root: Path, task: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """The person approved PLAN.md as it is now. A plan changed after the approval is not approved."""
    data = data if data is not None else read(root, task)
    current = plan_digest(root, task)
    return bool(data and current) and (data.get("plan") or {}).get("approved_sha256") == current
