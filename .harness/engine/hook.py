#!/usr/bin/env python3
"""The only hook entry point. One process per hook event.

  stdin  -> adapter (raw payload -> HookEvent)
         -> session state (locked) -> core subagent tracking
         -> modules from registry.json that subscribe to the event
         -> merge (deny > ask > allow; contexts joined; one block blocks)
  stdout <- adapter (Decision -> runtime output JSON)
  log    -> observe module: one line per call in the log of the session

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
from core import breaker  # noqa: E402
from core import callrecord  # noqa: E402
from core import registry as registry_module  # noqa: E402
from core import state as state_module  # noqa: E402
from core.context import Context  # noqa: E402
from core.events import Decision, HookEvent, merge  # noqa: E402
from core.failopen import call_safely  # noqa: E402
from core.logs import log_error  # noqa: E402
from core.paths import repo_root  # noqa: E402


def run_modules(root: Path, event: HookEvent, ctx: Context, names: List[str]) -> Tuple[List[Tuple[str, Decision]], List[str], Dict[str, Any]]:
    """Call each module. A module that raises has no opinion and its state changes are rolled back.

    Returns what each module decided (with its name), the modules that ran, and the facts they report for the log."""
    sources: List[Tuple[str, Decision]] = []
    ran: List[str] = []
    facts: Dict[str, Any] = {}
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
            sources.append((name, decision))
            facts.update(decision.facts)
    return sources, ran, facts


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
        sources, ran, facts = run_modules(root, event, ctx, names)
        decision = merge([item for _name, item in sources])
        denial = call_safely(root, "breaker", breaker.apply, root, state, event, decision, ctx.level)  # a refusal stays a refusal
        state_module.track_after(state, event, decision)
        level = ctx.level
        admin = ctx.admin
        parent_session_id = state.get("parent_session_id")
    record = callrecord.build(
        event,
        decision,
        engine=getattr(adapter, "engine", lambda _payload: "")(payload),
        ran=ran,
        sources=sources,
        facts=facts,
        level=level,
        parent_session_id=parent_session_id,
        denial=denial,
        admin=admin,
    )
    return adapter.render(event, decision), record


def observe(root: Path, record: Dict[str, Any], raw: str, output: Dict[str, Any]) -> None:
    """Hand the call record to the observe module, if it is on. Logging must never get in the way of the hook."""
    try:
        entry = registry_module.load_registry(root)["modules"].get("observe")
        if entry is None or not entry["enabled"] or entry["status"] == "retired":
            return
        importlib.import_module("modules.observe").record_call(root, record, raw, output)
    except Exception as error:
        log_error(root, "observe", error)


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
    observe(root, record, raw, output)
    sys.stdout.write(json.dumps(output))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
