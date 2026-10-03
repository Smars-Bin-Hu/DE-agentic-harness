"""gate hook handler. PreToolUse only. It guards writes and never blocks a read.

  edit / create tools   a guardrail file or a file only the CLI writes is denied; in L3 a path outside the request folder is denied
  terminal              a command that writes a guardrail file or is dangerous is denied; some commands ask a person
  `.git`                a path in a `.git` folder is denied at every Level, in a terminal command too (A4); so is a path a target
                        repository lists in refused_paths

A call with no path the gate can read is allowed: the gate only denies what it can see clearly (AGENTS.md).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from core import repo_paths, targets
from core.context import Context
from core.events import Decision, HookEvent

from . import rules, terminal
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
        for absolute in repo_paths.resolve(raw, ctx.root, event.cwd):
            if repo_paths.has_git_folder(absolute):
                return Decision(permission="deny", reason=rules.git_folder(absolute))
            hit = compiled.refused_match(absolute)
            if hit:
                return Decision(permission="deny", reason=rules.target_refused_file(*hit))
        readings = repo_paths.repo_relative(raw, ctx.root, event.cwd)
        for relative in (item for item in readings if item is not None):
            pattern = compiled.guardrail_match(relative)
            if pattern:
                return Decision(permission="deny", reason=rules.guardrail_file(relative, pattern))
            if compiled.owned_match(relative):
                return Decision(permission="deny", reason=rules.cli_owned_file(relative))
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
    why = terminal.owned_write(event.command, compiled)
    if why:
        return Decision(permission="deny", reason=rules.cli_owned_terminal(why))
    why = terminal.git_write(event.command, compiled)
    if why:
        return Decision(permission="deny", reason=rules.git_folder_terminal(why))
    verdict = terminal.check(event.command, compiled)
    if verdict is None:
        return None
    permission, why = verdict
    reason = rules.terminal_denied(why) if permission == "deny" else rules.terminal_ask(why)
    return Decision(permission=permission, reason=reason)


def target_repos(ctx: Context) -> List[Tuple[str, Path, List[str]]]:
    """The target repositories and their refused_paths. A broken target.json gives none: the `.git` floor still holds, and doctor reports it."""
    try:
        found = targets.load(ctx.root)
    except Exception:  # noqa: BLE001 - the gate must not fail on a bad target.json
        return []
    return [(repo.name, repo.path, repo.refused_paths) for repo in found.repos.values()]


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.event != "PreToolUse" or event.tool_kind not in WRITE_KINDS + ("terminal",):
        return None
    policy = ctx.policy(POLICY_NAME)
    validate_policy(policy, floor=False)
    compiled = Compiled(policy, target_repos(ctx))
    if event.tool_kind == "terminal":
        return check_terminal(event, compiled)
    return check_write(event, ctx, compiled)
