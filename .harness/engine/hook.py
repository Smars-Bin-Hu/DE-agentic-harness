#!/usr/bin/env python3
"""The only hook entry point. One process per hook event.

  stdin  -> adapter (raw payload -> HookEvent)
         -> session state (locked) -> core subagent tracking
         -> modules from registry.json that subscribe to the event
         -> merge (deny > ask > allow; contexts joined; one block blocks)
  stdout <- adapter (Decision -> runtime output JSON)

Any error: log it, print {} and exit 0. A broken hook must not block normal work.
"""

from __future__ import annotations

import copy
import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import adapters  # noqa: E402
from core import registry as registry_module  # noqa: E402
from core import state as state_module  # noqa: E402
from core.context import Context  # noqa: E402
from core.events import Decision, HookEvent, merge  # noqa: E402
from core.logs import log_call, log_error  # noqa: E402
from core.paths import repo_root  # noqa: E402


def run_modules(root: Path, event: HookEvent, ctx: Context, names: List[str]) -> Tuple[List[Decision], List[str]]:
    """Call each module. A module that raises has no opinion and its state changes are rolled back."""
    decisions: List[Decision] = []
    ran: List[str] = []
    for name in names:
        snapshot = copy.deepcopy(ctx.state)
        try:
            module = importlib.import_module(f"modules.{name}")
            decision = module.handle(event, ctx)
            ran.append(name)
        except Exception as error:
            log_error(root, f"module:{name}:{event.event}", error)
            ctx.state.clear()
            ctx.state.update(snapshot)
            decision = None
        if decision is not None:
            decisions.append(decision)
    return decisions, ran


def process(raw: str, root: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Payload text in, (runtime output, call record) out. Raises on any failure."""
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Hook payload is not a JSON object")
    adapter = adapters.detect(payload)
    event = adapter.parse(payload)
    registry = registry_module.load_registry(root)
    names = registry_module.modules_for(registry, event.event)
    link = None
    if event.event == "UserPromptSubmit" and not state_module.state_path(root, event.surface, event.session_id).exists():
        link = state_module.claim_child(root, event.surface, event)
    with state_module.session(root, event.surface, event.session_id) as state:
        state_module.track_before(state, event)
        if link:
            state.update(link)  # a subagent session: it inherits the parent's level, and its first prompt is not the user
            event.from_subagent = True
        ctx = Context(root, state)
        decisions, ran = run_modules(root, event, ctx, names)
        decision = merge(decisions)
        state_module.track_after(state, event, decision)
    outcome = decision.permission or ("block" if decision.block else ("context" if decision.context else "none"))
    record = {
        "surface": event.surface,
        "event": event.event,
        "session_id": event.session_id,
        "tool_name": event.tool_name,
        "agent_type": event.agent_type,
        "from_subagent": event.from_subagent,
        "continuation": event.continuation,
        "modules": ran,
        "decision": outcome,
    }
    return adapter.render(event, decision), record


def main() -> int:
    started = time.monotonic()
    root = repo_root()
    output: Dict[str, Any] = {}
    record: Dict[str, Any] = {}
    raw = ""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        output, record = process(raw, root)
    except BaseException as error:  # noqa: BLE001 - fail-open on everything, including SystemExit
        log_error(root, "hook", error, sample=raw)
        record = {"error": f"{type(error).__name__}: {error}"}
        output = {}
    record["ms"] = round((time.monotonic() - started) * 1000, 1)
    record["pid"] = os.getpid()
    log_call(root, record)
    sys.stdout.write(json.dumps(output))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
