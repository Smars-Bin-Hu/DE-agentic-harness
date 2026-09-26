#!/usr/bin/env python3
"""Task Level policy engine for GitHub Copilot hooks.

The engine intentionally does not make permission decisions for normal work.
It only denies subagent creation when the active Task Level disallows it.
All other budget limits are advisory and are emitted once after a successful tool use.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
RUNTIMES = {"copilot"}
COUNTER_NAMES = ("observed_tool_calls", "repository_searches", "subagents_created")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_root() -> Path:
    override = os.environ.get("TASK_POLICY_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def policy_path() -> Path:
    return repo_root() / ".harness" / "policies" / "task-levels.json"


def runtime_root() -> Path:
    return repo_root() / ".harness" / "runtime" / "task-policy"


def load_policy() -> dict[str, Any]:
    with policy_path().open(encoding="utf-8") as handle:
        policy = json.load(handle)
    if policy.get("schema_version") != SCHEMA_VERSION or not isinstance(policy.get("levels"), dict):
        raise ValueError("Invalid Task Level policy schema")
    for level in ("1", "2", "3"):
        budget = policy["levels"].get(level, {}).get("execution_budget", {})
        if not isinstance(budget, dict) or any(not isinstance(budget.get(name), int) for name in COUNTER_NAMES):
            raise ValueError(f"Invalid policy for level {level}")
    return policy


def validate_level(level: int, policy: dict[str, Any]) -> None:
    if str(level) not in policy["levels"]:
        raise ValueError(f"Unknown Task Level: {level}. Expected 1, 2, or 3.")


def safe_session_id(session_id: str) -> str:
    if not session_id:
        raise ValueError("session_id is required")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
    if safe in {"", ".", ".."}:
        digest = hashlib.sha256(session_id.encode()).hexdigest()[:16]
        safe = f"session-{digest}"
    return safe[:180]


def state_path(runtime: str, session_id: str) -> Path:
    if runtime not in RUNTIMES:
        raise ValueError(f"Unknown runtime: {runtime}")
    return runtime_root() / runtime / f"{safe_session_id(session_id)}.json"


def new_state(runtime: str, session_id: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime": runtime,
        "session_id": session_id,
        "task": {
            "id": None,
            "level": 1,
            "previous_level": None,
            "reason": "No active task. The next request starts at Level 1.",
            "status": "idle",
            "started_at": None,
            "completed_at": None,
            "updated_at": now,
            "transitions": [],
        },
        "counters": {name: 0 for name in COUNTER_NAMES},
        "warnings_emitted": [],
        "task_history": [],
    }


def validate_state(state: dict[str, Any], runtime: str, session_id: str) -> None:
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported Task Level state schema")
    if state.get("runtime") != runtime or state.get("session_id") != session_id:
        raise ValueError("Task Level state does not belong to this runtime/session")
    task = state.get("task")
    counters = state.get("counters")
    if not isinstance(task, dict) or not isinstance(counters, dict):
        raise ValueError("Invalid Task Level state")
    if task.get("level") not in (1, 2, 3) or task.get("status") not in {"idle", "active", "completed"}:
        raise ValueError("Invalid Task Level task state")
    if any(not isinstance(counters.get(name), int) or counters[name] < 0 for name in COUNTER_NAMES):
        raise ValueError("Invalid Task Level counters")


def read_state(path: Path, runtime: str, session_id: str) -> dict[str, Any]:
    if not path.exists():
        return new_state(runtime, session_id)
    with path.open(encoding="utf-8") as handle:
        state = json.load(handle)
    validate_state(state, runtime, session_id)
    return state


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


@contextmanager
def state_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + 5
    while True:
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for Task Level state lock: {lock_path}")
            time.sleep(0.01)
    try:
        yield
    finally:
        lock_path.rmdir()


def update_state(runtime: str, session_id: str, mutator: Any) -> dict[str, Any]:
    path = state_path(runtime, session_id)
    with state_lock(path):
        state = read_state(path, runtime, session_id)
        mutator(state)
        state["task"]["updated_at"] = utc_now()
        atomic_write(path, state)
        return state


def archive_current_task(state: dict[str, Any], completion_reason: str) -> None:
    task = state["task"]
    if not task.get("id"):
        return
    archived = copy.deepcopy(task)
    if task["status"] == "active":
        archived["status"] = "completed"
        archived["completed_at"] = utc_now()
        archived["completion_reason"] = completion_reason
    elif not archived.get("completion_reason"):
        archived["completion_reason"] = completion_reason
    state["task_history"].append(archived)
    state["task_history"] = state["task_history"][-10:]


def begin_task(state: dict[str, Any], reason: str, replace: bool = False) -> None:
    if state["task"]["status"] == "active":
        if not replace:
            raise ValueError("An active task already exists; use begin --replace to replace it.")
        archive_current_task(state, "replaced")
    elif state["task"].get("id"):
        archive_current_task(state, "superseded by new user request")
    now = utc_now()
    state["task"] = {
        "id": f"task-{uuid.uuid4()}",
        "level": 1,
        "previous_level": None,
        "reason": reason,
        "status": "active",
        "started_at": now,
        "completed_at": None,
        "updated_at": now,
        "transitions": [
            {
                "type": "begin",
                "from_level": None,
                "to_level": 1,
                "reason": reason,
                "at": now,
            }
        ],
    }
    state["counters"] = {name: 0 for name in COUNTER_NAMES}
    state["warnings_emitted"] = []


def ensure_active_task(state: dict[str, Any], reason: str) -> None:
    if state["task"]["status"] != "active":
        begin_task(state, reason)


def set_level(state: dict[str, Any], level: int, reason: str, policy: dict[str, Any]) -> None:
    validate_level(level, policy)
    ensure_active_task(state, "Task was initialized lazily at Level 1.")
    task = state["task"]
    old_level = task["level"]
    if old_level == level:
        task["reason"] = reason
        return
    now = utc_now()
    task["previous_level"] = old_level
    task["level"] = level
    task["reason"] = reason
    task["transitions"].append(
        {
            "type": "upgrade" if level > old_level else "downgrade",
            "from_level": old_level,
            "to_level": level,
            "reason": reason,
            "at": now,
        }
    )


def complete_task(state: dict[str, Any], reason: str) -> None:
    ensure_active_task(state, "Task was initialized lazily at Level 1.")
    task = state["task"]
    now = utc_now()
    task["transitions"].append(
        {
            "type": "complete",
            "from_level": task["level"],
            "to_level": 1,
            "reason": reason,
            "at": now,
        }
    )
    task["previous_level"] = task["level"]
    task["level"] = 1
    task["reason"] = reason
    task["status"] = "completed"
    task["completed_at"] = now


def input_value(payload: dict[str, Any], snake: str, camel: str) -> Any:
    return payload.get(snake, payload.get(camel))


def hook_session_id(payload: dict[str, Any]) -> str:
    value = input_value(payload, "session_id", "sessionId")
    if not isinstance(value, str) or not value:
        raise ValueError("Hook payload does not include session_id")
    return value


def tool_name(payload: dict[str, Any]) -> str:
    value = input_value(payload, "tool_name", "toolName")
    return value if isinstance(value, str) else ""


def tool_input(payload: dict[str, Any]) -> Any:
    return input_value(payload, "tool_input", "toolArgs")


def command_from_input(value: Any) -> str:
    if isinstance(value, dict):
        command = value.get("command")
        return command if isinstance(command, str) else ""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        return command_from_input(decoded)
    return ""


def is_policy_control_call(name: str, value: Any) -> bool:
    if name.lower() not in {"bash", "shell", "exec_command"}:
        return False
    command = command_from_input(value)
    return "task_policy.py" in command and any(
        token in command for token in (" begin", " set-level", " complete", " status")
    )


def is_subagent_tool(name: str) -> bool:
    return name.lower() in {"agent", "spawn_agent", "task", "subagent"}


def is_repository_search(name: str, value: Any) -> bool:
    if name.lower() in {"grep", "glob", "rg"}:
        return True
    if name.lower() not in {"bash", "shell", "exec_command"}:
        return False
    command = command_from_input(value)
    return bool(re.search(r"(?:^|[;&|]\s*)(?:rg|grep|git\s+grep|find)\b", command))


def deny_output(runtime: str, reason: str) -> dict[str, Any]:
    return {"permissionDecision": "deny", "permissionDecisionReason": reason}


def warning_output(runtime: str, text: str) -> dict[str, Any]:
    return {"additionalContext": text}


def session_context(runtime: str, event: str, state: dict[str, Any]) -> dict[str, Any]:
    task = state["task"]
    text = (
        "Task Level policy is active. "
        f"Session id: {state['session_id']}. "
        f"Current status: {task['status']}; level: {task['level']}. "
        "Use the task-level-policy skill to classify a new task or change levels. "
        "Complete the active task before giving a final completion response."
    )
    return {"additionalContext": text}


def handle_session_event(runtime: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    session_id = hook_session_id(payload)
    if event == "SessionStart":
        state = update_state(runtime, session_id, lambda state: None)
    elif event == "UserPromptSubmit":
        def mutate(state: dict[str, Any]) -> None:
            if state["task"]["status"] != "active":
                begin_task(state, "New user request defaults to Level 1.")
        state = update_state(runtime, session_id, mutate)
    else:
        raise ValueError(f"Unsupported session event: {event}")
    return session_context(runtime, event, state)


def handle_pre_tool_use(runtime: str, payload: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    session_id = hook_session_id(payload)
    name = tool_name(payload)
    value = tool_input(payload)
    decision: dict[str, Any] = {}

    def mutate(state: dict[str, Any]) -> None:
        nonlocal decision
        ensure_active_task(state, "Tool use before task initialization defaults to Level 1.")
        if is_policy_control_call(name, value):
            return
        task = state["task"]
        level_policy = policy["levels"][str(task["level"])]
        budget = level_policy["execution_budget"]
        if is_subagent_tool(name):
            if not level_policy["subagents"]["allowed"]:
                decision = deny_output(
                    runtime,
                    f"Subagent creation is not allowed under Task Level {task['level']}. "
                    "Escalate the task level before delegating.",
                )
                return
            if state["counters"]["subagents_created"] >= budget["subagents_created"]:
                decision = deny_output(
                    runtime,
                    f"Task Level {task['level']} allows at most {budget['subagents_created']} subagents. "
                    "Complete existing work or change the task policy before creating another.",
                )
                return
            state["counters"]["subagents_created"] += 1
        state["counters"]["observed_tool_calls"] += 1
        if is_repository_search(name, value):
            state["counters"]["repository_searches"] += 1

    update_state(runtime, session_id, mutate)
    return decision


def handle_post_tool_use(runtime: str, payload: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    session_id = hook_session_id(payload)
    messages: list[str] = []

    def mutate(state: dict[str, Any]) -> None:
        if state["task"]["status"] != "active":
            return
        level = state["task"]["level"]
        budget = policy["levels"][str(level)]["execution_budget"]
        for name in ("repository_searches", "observed_tool_calls"):
            current = state["counters"][name]
            maximum = budget[name]
            marker = f"level-{level}:{name}"
            if current >= math.ceil(maximum * 0.8) and marker not in state["warnings_emitted"]:
                status = "has exceeded" if current > maximum else "has reached"
                messages.append(
                    f"Task Level {level} {status} its soft {name} budget: {current}/{maximum}. "
                    "Finish the focused work, or escalate if the task scope genuinely requires more autonomy."
                )
                state["warnings_emitted"].append(marker)

    update_state(runtime, session_id, mutate)
    return warning_output(runtime, "\n\n".join(messages)) if messages else {}


def handle_hook(runtime: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    policy = load_policy()
    if event in {"SessionStart", "UserPromptSubmit"}:
        return handle_session_event(runtime, event, payload)
    if event == "PreToolUse":
        return handle_pre_tool_use(runtime, payload, policy)
    if event == "PostToolUse":
        return handle_post_tool_use(runtime, payload, policy)
    raise ValueError(f"Unsupported hook event: {event}")


def log_hook_error(runtime: str, event: str, error: BaseException) -> None:
    try:
        root = runtime_root()
        root.mkdir(parents=True, exist_ok=True)
        record = {
            "at": utc_now(),
            "runtime": runtime,
            "event": event,
            "error": str(error),
            "traceback": traceback.format_exc(),
        }
        with (root / "hook-errors.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except Exception:
        pass


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    path = state_path(args.runtime, args.session_id)
    with state_lock(path):
        state = read_state(path, args.runtime, args.session_id)
        atomic_write(path, state)
    return state


def command_begin(args: argparse.Namespace) -> dict[str, Any]:
    return update_state(
        args.runtime,
        args.session_id,
        lambda state: begin_task(state, args.reason, args.replace),
    )


def command_set_level(args: argparse.Namespace) -> dict[str, Any]:
    policy = load_policy()
    return update_state(
        args.runtime,
        args.session_id,
        lambda state: set_level(state, args.level, args.reason, policy),
    )


def command_complete(args: argparse.Namespace) -> dict[str, Any]:
    return update_state(
        args.runtime,
        args.session_id,
        lambda state: complete_task(state, args.reason),
    )


def add_session_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runtime", required=True, choices=sorted(RUNTIMES))
    parser.add_argument("--session-id", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task Level policy engine")
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="show task state")
    add_session_arguments(status)
    status.set_defaults(handler=command_status)

    begin = commands.add_parser("begin", help="begin a Level 1 task")
    add_session_arguments(begin)
    begin.add_argument("--reason", required=True)
    begin.add_argument("--replace", action="store_true")
    begin.set_defaults(handler=command_begin)

    set_level_command = commands.add_parser("set-level", help="transition the active task")
    add_session_arguments(set_level_command)
    set_level_command.add_argument("--level", required=True, type=int)
    set_level_command.add_argument("--reason", required=True)
    set_level_command.set_defaults(handler=command_set_level)

    complete = commands.add_parser("complete", help="complete the active task")
    add_session_arguments(complete)
    complete.add_argument("--reason", required=True)
    complete.set_defaults(handler=command_complete)

    hook = commands.add_parser("hook", help="handle a runtime hook payload from stdin")
    hook.add_argument("--runtime", required=True, choices=sorted(RUNTIMES))
    hook.add_argument("--event", required=True, choices=["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"])
    hook.set_defaults(handler=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "hook":
        try:
            payload = json.load(sys.stdin)
            print(json.dumps(handle_hook(args.runtime, args.event, payload)))
        except Exception as error:
            log_hook_error(args.runtime, args.event, error)
            # Hooks are a guardrail rather than a permission system: unexpected
            # engine failures must not block regular tool calls.
            print("{}")
        return 0
    try:
        result = args.handler(args)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"task-policy: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
