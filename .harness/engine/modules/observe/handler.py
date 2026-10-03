"""observe: writes the call log. hook.py calls `record_call` after the decision is merged, so the record has the final
decision and the time it took. The module subscribes to no event: it has no opinion on any call, and it never changes one.

A broken policy does not stop the log: the defaults are used. A broken log does not stop the hook: hook.py catches it.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core import config
from core.context import Context
from core.events import Decision, HookEvent
from core.logs import log_call, safe_name
from core.paths import runtime_dir

from .policy import DEFAULTS, POLICY_NAME, validate_policy

NAME = "observe"


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    return None


def load_policy(root: Path) -> Dict[str, Any]:
    try:
        policy = config.load_policy(root, POLICY_NAME)
        validate_policy(policy)
        return policy
    except Exception:
        return DEFAULTS


def clip(text: Any, limit: int) -> Any:
    if isinstance(text, str) and len(text) > limit:
        return text[:limit] + "…"
    return text


def clip_record(record: Dict[str, Any], limit: int) -> Dict[str, Any]:
    clipped = dict(record)
    if "reason" in record:
        clipped["reason"] = clip(record["reason"], limit)
    target = record.get("target")
    if isinstance(target, dict):
        clipped["target"] = {"paths": [clip(item, limit) for item in target.get("paths", [])], "command": clip(target.get("command", ""), limit)}
    return clipped


def capture(root: Path, record: Dict[str, Any], raw: str, output: Dict[str, Any]) -> None:
    """The raw input and output of one call, for finding out what a runtime really sends. Off by default: the input holds code."""
    now = datetime.now(timezone.utc)
    directory = runtime_dir(root) / "capture" / safe_name(str(record.get("surface") or "unknown"))
    directory.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    data = {
        "captured_at": now.isoformat(),
        "argv_event": record.get("event", ""),
        "surface": record.get("surface", ""),
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "python": sys.version.split()[0],
        "env_names": sorted(os.environ.keys()),  # names only, never values
        "stdin_raw": raw,
        "stdin_json": payload if isinstance(payload, dict) else None,
        "hook_output": output,
    }
    name = f"{now.strftime('%Y%m%dT%H%M%S.%f')}-{record.get('event', 'unknown')}-{os.getpid()}.json"
    (directory / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_call(root: Path, record: Dict[str, Any], raw: str = "", output: Optional[Dict[str, Any]] = None) -> None:
    policy = load_policy(root)
    log_call(root, clip_record(record, policy["max_text_chars"]))
    if policy["capture"]["enabled"]:
        capture(root, record, raw, output or {})
