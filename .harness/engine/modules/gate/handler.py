"""gate hook handler. PreToolUse only. It guards writes and never blocks a read.

  edit / create tools   a guardrail file or a file only the CLI writes is denied; in L3 a path outside the request folder is denied
  terminal              a command that writes a guardrail file or is dangerous is denied; some commands ask a person
  git commands          with target repositories configured (A5): a git read passes, a write is refused until a person approves that exact command
                        (`approve-command`), some are never approved (push, clean, reset --hard, branch -D, any force)
  `.git`                a path in a `.git` folder is denied at every Level, in a terminal command too (A4); so is a path a target
                        repository lists in refused_paths

A call with no path the gate can read is allowed: the gate only denies what it can see clearly (AGENTS.md).
"""

from __future__ import annotations

import re
from typing import Optional

from core import repo_paths, targets
from core.context import Context
from core.events import Decision, HookEvent

from . import approvals, gitcmd, rules, terminal
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


def check_terminal(event: HookEvent, ctx: Context, compiled: Compiled, policy: dict, guard_git: bool) -> Optional[Decision]:
    why = terminal.guardrail_write(event.command, compiled)
    if why:
        return Decision(permission="deny", reason=rules.guardrail_terminal(why))
    why = terminal.owned_write(event.command, compiled)
    if why:
        return Decision(permission="deny", reason=rules.cli_owned_terminal(why))
    why = terminal.git_write(event.command, compiled)
    if why:
        return Decision(permission="deny", reason=rules.git_folder_terminal(why))
    git = gitcmd.classify(event.command) if guard_git else gitcmd.Verdict()
    if git.kind == gitcmd.NEVER:
        return Decision(permission="deny", reason=rules.git_never(git.why, gitcmd.collapse(event.command)))
    verdict = terminal.check(event.command, compiled)
    if verdict is not None and verdict[0] == "deny":
        return Decision(permission="deny", reason=rules.terminal_denied(verdict[1]))
    if git.kind == gitcmd.APPROVE:
        minutes = approvals.minutes(policy)
        if approvals.consume(ctx.root, event.session_id, event.command, minutes):
            return None  # the person read this command and approved it
        code = approvals.request(ctx.root, event.surface, event.session_id, event.command, minutes)
        return Decision(permission="deny", reason=rules.git_needs_approval(git.why, gitcmd.collapse(event.command), code, minutes), facts={"kind": "git-approval"})
    if verdict is None:
        return None
    permission, why = verdict
    reason = rules.terminal_denied(why) if permission == "deny" else rules.terminal_ask(why)
    return Decision(permission=permission, reason=reason)


def load_targets(ctx: Context) -> Optional[targets.Targets]:
    """The target repositories. A broken target.json gives None: the `.git` floor still holds, and doctor reports it."""
    try:
        return targets.load(ctx.root)
    except Exception:  # noqa: BLE001 - the gate must not fail on a bad target.json
        return None


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    if event.event != "PreToolUse" or event.tool_kind not in WRITE_KINDS + ("terminal",):
        return None
    policy = ctx.policy(POLICY_NAME)
    validate_policy(policy, floor=False)
    found = load_targets(ctx)
    compiled = Compiled(policy, [(repo.name, repo.path, repo.refused_paths) for repo in found.repos.values()] if found else None)
    if event.tool_kind == "terminal":
        # Without target repositories the harness behaves as before: only the ask rules in gate.json look at git.
        return check_terminal(event, ctx, compiled, policy, guard_git=bool(found and found.configured))
    return check_write(event, ctx, compiled)
