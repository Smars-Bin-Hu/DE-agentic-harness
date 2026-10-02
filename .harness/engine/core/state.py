"""Per-session state: lock, atomic write, shared fields, subagent tracking.

State file: .harness/runtime/state/<surface>/<session>.json

Shared fields (one writer each, see 00 section 8.3):
  level           1 or 2, the level the user chose. Written by task_level.
  active_request  id of the running L3 request. Written by the request module.
Module state lives in state["modules"][<name>].
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

from . import breaker, schema
from .events import Decision, HookEvent
from .paths import state_dir, utc_now

SCHEMA_VERSION = 2
LOCK_TIMEOUT_SECONDS = 7.0
# A critical section takes milliseconds. A lock older than this belongs to a killed process (I-9).
LOCK_STALE_SECONDS = 5.0
# Safety nets so a missing SubagentStop cannot make the session ignore the user forever.
SUBAGENT_ACTIVE_TTL_SECONDS = 1800.0
PENDING_PROMPT_TTL_SECONDS = 300.0
PENDING_PROMPT_MAX = 8
# After a Stop block the SDK engine sends the reason back as a new UserPromptSubmit, within moments.
CONTINUATION_TTL_SECONDS = 120.0
# A subagent session (Copilot SDK engine) sends its first UserPromptSubmit within moments of its SubagentStart.
CHILD_CLAIM_SECONDS = 10.0
CHILD_SCAN_FILES = 30
CHILD_SCAN_AGE_SECONDS = 600.0
# Events core needs even when no module subscribes (subagent tracking). The hook config must cover them.
TRACKED_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "SubagentStart", "SubagentStop", "Stop")

STATE_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "surface", "session_id", "level", "active_request", "subagents", "modules"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [SCHEMA_VERSION]},
        "surface": {"type": "string"},
        "session_id": {"type": "string"},
        "level": {"type": "integer", "enum": [1, 2]},
        "active_request": {"type": ["string", "null"]},
        "subagents": {
            "type": "object",
            "required": ["active", "pending_prompts"],
            "properties": {
                "active": {"type": "array", "items": {"type": "object", "required": ["agent_id", "at"]}},
                "pending_prompts": {"type": "array", "items": {"type": "object", "required": ["prompt", "at"]}},
            },
        },
        "modules": {"type": "object"},
    },
}


def safe_session_id(session_id: str) -> str:
    if not session_id:
        raise ValueError("session_id is required")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
    if safe in {"", ".", ".."}:
        safe = "session-" + hashlib.sha256(session_id.encode()).hexdigest()[:16]
    return safe[:180]


def state_path(root: Path, surface: str, session_id: str) -> Path:
    return state_dir(root, surface) / f"{safe_session_id(session_id)}.json"


def new_state(surface: str, session_id: str) -> Dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "surface": surface,
        "session_id": session_id,
        "created_at": now,
        "updated_at": now,
        "level": 1,
        "active_request": None,
        "subagents": {"active": [], "pending_prompts": []},
        "modules": {},
    }


def validate_state(state: Any, surface: str, session_id: str) -> None:
    schema.check(state, STATE_SCHEMA, "session state")
    if state["surface"] != surface or state["session_id"] != session_id:
        raise ValueError("Session state does not belong to this surface/session")


def read_state(path: Path, surface: str, session_id: str) -> Dict[str, Any]:
    if not path.exists():
        return new_state(surface, session_id)
    with path.open(encoding="utf-8") as handle:
        state = json.load(handle)
    validate_state(state, surface, session_id)
    return state


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        temporary = handle.name
    try:
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _clear_if_stale(lock: Path) -> None:
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return
    if age > LOCK_STALE_SECONDS:
        try:
            os.rmdir(str(lock))
        except OSError:
            pass


@contextmanager
def state_lock(path: Path) -> Iterator[None]:
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            _clear_if_stale(lock)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for state lock: {lock}")
            time.sleep(0.01)
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


@contextmanager
def session(root: Path, surface: str, session_id: str) -> Iterator[Dict[str, Any]]:
    """Lock the session, yield its state, write it back if the block finishes without an exception."""
    path = state_path(root, surface, session_id)
    with state_lock(path):
        state = read_state(path, surface, session_id)
        yield state
        state["updated_at"] = utc_now()
        atomic_write(path, state)


def update_state(root: Path, surface: str, session_id: str, mutator: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    with session(root, surface, session_id) as state:
        mutator(state)
    return state


def effective_level(state: Dict[str, Any]) -> int:
    """3 while an L3 request is active, otherwise the level the user chose."""
    return 3 if state.get("active_request") else state["level"]


# --- subagent tracking (00 section 2, hard conclusion 5) -------------------------------------------


def _prune(state: Dict[str, Any], now: float) -> None:
    subagents = state["subagents"]
    subagents["active"] = [a for a in subagents["active"] if now - a["at"] <= SUBAGENT_ACTIVE_TTL_SECONDS]
    subagents["pending_prompts"] = [
        p for p in subagents["pending_prompts"] if now - p["at"] <= PENDING_PROMPT_TTL_SECONDS
    ]


def track_before(state: Dict[str, Any], event: HookEvent) -> None:
    """Update subagent bookkeeping before modules run. Sets event.from_subagent."""
    now = time.time()
    _prune(state, now)
    subagents = state["subagents"]
    name = event.event
    if name == "SessionStart":
        subagents["active"] = []
        subagents["pending_prompts"] = []
        breaker.reset(state)
    elif name == "SubagentStart":
        if event.agent_id:
            if not any(a["agent_id"] == event.agent_id for a in subagents["active"]):
                subagents["active"].append({"agent_id": event.agent_id, "agent_type": event.agent_type, "at": now})
        else:
            # Copilot SDK engine: no agent id yet. The subagent runs in a session of its own, which claims this entry.
            subagents["active"].append(
                {"agent_id": f"{event.agent_type}@{now:.3f}", "agent_type": event.agent_type, "at": now, "awaiting_child": True}
            )
    elif name == "SubagentStop":
        active = subagents["active"]
        index = next((i for i, a in enumerate(active) if a["agent_id"] == event.agent_id), None)
        if index is None:  # the SDK engine reports the child's session id here, not the id we made up
            index = next((i for i, a in enumerate(active) if a["agent_type"] == event.agent_type), None)
        if index is not None:
            del active[index]
    elif name == "Stop":
        # The main agent is finishing, so no subagent can still be running.
        subagents["active"] = []
    elif name == "UserPromptSubmit":
        if state.get("parent_session_id"):
            # A subagent session never receives a user prompt. Its later prompts are the engine feeding back a
            # SubagentStop block reason (recorded 2026-10-01).
            event.from_subagent = True
            return
        text = event.prompt.strip()
        waiting = state.get("continuation")
        if waiting and now - waiting["at"] <= CONTINUATION_TTL_SECONDS:
            reason = waiting["prompt"].strip()
            if text and reason and (text in reason or reason in text):
                state["continuation"] = None
                event.continuation = True
                return
        matched = next((p for p in subagents["pending_prompts"] if p["prompt"].strip() == text), None)
        if matched is not None:
            subagents["pending_prompts"].remove(matched)
            event.from_subagent = True
        elif subagents["active"]:
            event.from_subagent = True
        else:
            breaker.reset(state)  # a real user prompt opens a new window for counting repeated denies


def claim_child(root: Path, surface: str, event: HookEvent) -> Optional[Dict[str, Any]]:
    """Copilot SDK engine: a subagent runs in its own session. Is this new session one?

    Called for the first UserPromptSubmit of a session that has no state yet. A parent that just reported a
    SubagentStart is waiting for its child. Match by the call message first, then by time. On a match the parent's
    entry is marked as claimed, and its level and request are returned for the child to inherit.
    """
    directory = state_dir(root, surface)
    if not directory.is_dir():
        return None
    now = time.time()
    own = safe_session_id(event.session_id)
    files = sorted(
        (p for p in directory.glob("*.json") if p.stem != own),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:CHILD_SCAN_FILES]
    text = event.prompt.strip()
    best = None  # (score, parent path, parent session id)
    for path in files:
        try:
            if now - path.stat().st_mtime > CHILD_SCAN_AGE_SECONDS:
                continue
            with path.open(encoding="utf-8") as handle:
                parent = json.load(handle)
            waiting = [a for a in parent["subagents"]["active"] if a.get("awaiting_child") and now - a["at"] <= CHILD_CLAIM_SECONDS]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not waiting:
            continue
        by_message = any(p["prompt"].strip() == text for p in parent["subagents"]["pending_prompts"])
        score = (2 if by_message else 1, max(a["at"] for a in waiting))
        if best is None or score > best[0]:
            best = (score, path, parent["session_id"])
    if best is None:
        return None
    _, path, parent_id = best
    claimed: Dict[str, Any] = {}

    def mark(parent: Dict[str, Any]) -> None:
        for entry in parent["subagents"]["active"]:
            if entry.get("awaiting_child"):
                entry["awaiting_child"] = False
                entry["child_session_id"] = event.session_id
                break
        claimed.update(parent_session_id=parent["session_id"], level=parent["level"], active_request=parent["active_request"])

    with state_lock(path):
        parent_state = read_state(path, surface, parent_id)
        mark(parent_state)
        atomic_write(path, parent_state)
    return claimed


def track_after(state: Dict[str, Any], event: HookEvent, decision: Decision) -> None:
    """Remember what core must recognize later: the call message of an allowed subagent call, and a Stop block reason."""
    if event.event == "Stop" and decision.block and decision.reason:
        state["continuation"] = {"prompt": decision.reason, "at": time.time()}
        return
    if event.event != "PreToolUse" or event.tool_kind != "subagent" or decision.permission == "deny":
        return
    if not event.subagent_prompt:
        return
    pending = state["subagents"]["pending_prompts"]
    pending.append({"prompt": event.subagent_prompt, "agent": event.subagent_target, "at": time.time()})
    del pending[:-PENDING_PROMPT_MAX]
