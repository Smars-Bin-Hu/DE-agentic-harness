"""`cli stats`: counts and times from the session logs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logs import read_lines, session_files
from core.paths import logs_dir, utc_now


RECENT_SESSIONS = 5


def percentile(values: List[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))] if ordered else 0.0


def timing(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"calls": 0, "mean_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    return {
        "calls": len(values),
        "mean_ms": round(sum(values) / len(values), 1),
        "p95_ms": round(percentile(values, 0.95), 1),
        "max_ms": round(max(values), 1),
    }


def bump(table: Dict[str, int], key: str) -> None:
    table[key] = table.get(key, 0) + 1


DOUBLE_RUN_SECONDS = 0.15
SAME_CALL_FIELDS = ("event", "tool_name", "tool_kind", "decision", "from_subagent")


def seconds_between(first: str, second: str) -> float:
    try:
        return abs((datetime.fromisoformat(second) - datetime.fromisoformat(first)).total_seconds())
    except (TypeError, ValueError):
        return 1e9


def same_call_twice(previous: Dict[str, Any], row: Dict[str, Any]) -> bool:
    """Two rows of one session for the same event and tool within a moment, from two processes: the hook may be configured twice.

    Two real tool calls of the same kind at the same moment look the same, so this is a hint, not proof.
    """
    if not previous or previous.get("pid") == row.get("pid"):
        return False
    if any(previous.get(field) != row.get(field) for field in SAME_CALL_FIELDS):
        return False
    return seconds_between(previous.get("at", ""), row.get("at", "")) < DOUBLE_RUN_SECONDS


def collect(root: Path, session_id: str = "", surface: str = "", days: Optional[int] = None) -> Dict[str, Any]:
    """Numbers over the matching sessions. `days` keeps only the calls of the last N days."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days is not None else ""
    rows: List[Dict[str, Any]] = []
    sessions = set()
    doubles = 0
    for found_surface, path in session_files(root):
        if surface and found_surface != surface:
            continue
        if session_id and path.stem != session_id:
            continue
        previous: Dict[str, Any] = {}
        for row in read_lines(path):
            if since and row.get("at", "") < since:
                continue
            if same_call_twice(previous, row):
                doubles += 1
            previous = row
            rows.append(row)
            sessions.add((found_surface, path.stem))

    prompts: Dict[str, int] = {}
    tool_calls: Dict[str, int] = {}
    refused: Dict[str, int] = {}
    asked: Dict[str, int] = {}
    blocked: Dict[str, int] = {}
    budget_denials = 0
    verifier: Dict[str, int] = {}
    subagents: Dict[str, int] = {}
    by_event: Dict[str, List[float]] = {}
    every: List[float] = []
    for row in rows:
        event = row.get("event", "")
        level = f"L{row.get('level', 1)}"
        if event == "UserPromptSubmit" and not row.get("from_subagent") and not row.get("continuation"):
            bump(prompts, level)
        elif event == "PreToolUse":
            bump(tool_calls, level)
        elif event == "SubagentStart":
            bump(subagents, row.get("agent_type") or "default")
        decision = row.get("decision")
        owners = ",".join(row.get("by") or []) or "unknown"
        if decision == "deny":
            bump(refused, owners)
            if row.get("kind") == "budget":
                budget_denials += 1
        elif decision == "ask":
            bump(asked, owners)
        elif decision == "block":
            bump(blocked, owners)
        if row.get("judge") == "verifier":
            bump(verifier, row.get("verdict") or "unknown")
        if isinstance(row.get("ms"), (int, float)):
            by_event.setdefault(event, []).append(float(row["ms"]))
            every.append(float(row["ms"]))
    recent = []
    for found_surface, path in reversed(list(session_files(root))[-RECENT_SESSIONS:]):
        if surface and found_surface != surface:
            continue
        if session_id and path.stem != session_id:
            continue
        lines = read_lines(path)
        if lines:
            recent.append({
                "surface": found_surface, "session_id": path.stem, "first_call": lines[0].get("at", ""), "calls": len(lines),
                "highest_level": max(int(row.get("level", 1)) for row in lines),
                "subagent_session": bool(lines[0].get("parent_session_id")),
            })
    errors = [row for row in read_lines(logs_dir(root) / "hook-errors.jsonl") if not since or row.get("at", "") >= since]
    return {
        "sessions": len(sessions),
        "calls": len(rows),
        "prompts_by_level": prompts,
        "tool_calls_by_level": tool_calls,
        "denied_by_module": refused,
        "budget_denials": budget_denials,
        "asked_by_module": asked,
        "stop_blocks_by_module": blocked,
        "verifier_verdicts": verifier,
        "subagents_started": subagents,
        "hook_time": timing(every),
        "hook_time_by_event": {name: timing(values) for name, values in sorted(by_event.items())},
        "possible_double_runs": doubles,
        "recent_sessions": recent,
        "hook_errors": len(errors),
        "as_of": utc_now(),
    }
