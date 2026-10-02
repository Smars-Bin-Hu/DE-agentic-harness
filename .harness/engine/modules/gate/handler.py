"""gate hook handler. PreToolUse only. It guards writes and never blocks a read.

  edit / create tools   a guardrail file is denied at every level; in L3 a path outside the request folder is denied
  terminal              a command that writes a guardrail file or is dangerous is denied; some commands ask a person

A call with no path the gate can read is allowed: the gate only denies what it can see clearly (AGENTS.md).
"""

from __future__ import annotations

import re
from typing import Optional

from core.context import Context
from core.events import Decision, HookEvent

from . import repo_paths, rules, terminal
from .policy import POLICY_NAME, Compiled, validate_policy

NAME = "gate"
WRITE_KINDS = ("edit", "create")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def check_write(event: HookEvent, ctx: Context, compiled: Compiled) -> Optional[Decision]:
    request_id = ctx.state.get("active_request") if ctx.level == 3 else None
    request_root = ""
    if request_id:
        if not _REQUEST_ID.match(request_id) or ".." in request_id:
            return Decision(permission="deny", reason=rules.bad_request_id(request_id))
        request_root = compiled.request_root(request_id)
    outside: Optional[Decision] = None
    for raw in event.paths:
        readings = repo_paths.repo_relative(raw, ctx.root, event.cwd)
        for relative in (item for item in readings if item is not None):
            pattern = compiled.guardrail_match(relative)
            if pattern:
                return Decision(permission="deny", reason=rules.guardrail_file(relative, pattern))
        if request_id and outside is None and readings:
            stray = [item for item in readings if item is None or not _within(item, request_root)]
            if stray:
                shown = next((item for item in stray if item is not None), None)
                reason = (
                    rules.outside_request(shown, request_id, request_root)
                    if shown is not None
                    else rules.outside_repo_in_request(request_id, request_root)
                )
                outside = Decision(permission="deny", reason=reason)
    return outside


def _within(relative: str, folder: str) -> bool:
    relative, folder = relative.lower(), folder.lower().rstrip("/")
    return relative == folder or relative.startswith(folder + "/")


def check_terminal(event: HookEvent, compiled: Compiled) -> Optional[Decision]:
    why = terminal.guardrail_write(event.command, compiled)
    if why:
        return Decision(permission="deny", reason=rules.guardrail_terminal(why))
    verdict = terminal.check(event.command, compiled)
    if verdict is None:
        return None
    permission, why = verdict
    reason = rules.terminal_denied(why) if permission == "deny" else rules.terminal_ask(why)
    return Decision(permission=permission, reason=reason)


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.event != "PreToolUse" or event.tool_kind not in WRITE_KINDS + ("terminal",):
        return None
    policy = ctx.policy(POLICY_NAME)
    validate_policy(policy)
    compiled = Compiled(policy)
    if event.tool_kind == "terminal":
        return check_terminal(event, compiled)
    return check_write(event, ctx, compiled)
