"""CLI commands of the request module.

  request new|add-input|set-branch|set-status|wait|show|list|approve-promote|recover    the request itself (approve-promote, recover: a person at a terminal)
  brief set                                  hand the knowledge brief to the CLI
  attempt new                                open the next attempt
  dispatch                                   build and freeze the input package of one role
  handoff submit                             write a role's handoff
  report                                     one Markdown page about a request (also written when it is concluded)
  check                                      does the request folder agree with itself
  promote                                    copy the reviewed result back into the repository (ask in the gate)
  target list|show                           the target repositories (policy target.json): where they are, what their base branch is
"""

from __future__ import annotations

import argparse
from typing import Any, Dict

from core import targets
from core.paths import repo_root

from . import check, ops, promote, report


def _request(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--request", required=True, help="request id (from `request new`)")


def cmd_new(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.new_request(repo_root(), args.title, args.session_id, args.surface, args.task, args.branch)


def cmd_set_branch(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.set_branch(repo_root(), args.request, args.branch)


def cmd_add_input(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.add_input(repo_root(), args.request, args.paths, args.from_target)


def cmd_set_status(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.set_status(repo_root(), args.request, args.status, args.reason)


def cmd_wait(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.wait(repo_root(), args.request, args.reason)


def cmd_approve_promote(args: argparse.Namespace) -> Dict[str, Any]:
    return promote.approve(repo_root(), args.request or "")


def cmd_recover(args: argparse.Namespace) -> Dict[str, Any]:
    return promote.recover(repo_root(), args.request or "")


def cmd_report(args: argparse.Namespace) -> Dict[str, Any]:
    return report.generate(repo_root(), args.request or "")


def cmd_list(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.list_requests(repo_root(), args.status or "")


def cmd_show(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.show(repo_root(), args.request)


def cmd_brief_set(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.set_brief(repo_root(), args.request, args.file)


def cmd_attempt_new(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.new_attempt(repo_root(), args.request, args.human_approved)


def cmd_dispatch(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.dispatch(repo_root(), args.request, args.role, args.input, args.from_target)


def cmd_handoff_submit(args: argparse.Namespace) -> Dict[str, Any]:
    return ops.submit_handoff(
        repo_root(), args.request, args.role, args.status, args.summary,
        outputs=args.output, evidence=args.evidence, blockers=args.blocker, next_step=args.next, kb_additions=args.kb_addition,
    )


def cmd_check(args: argparse.Namespace) -> Dict[str, Any]:
    result = check.run(repo_root(), args.request, args.require_conclusion)
    if not result["ok"]:
        result["exit_code"] = 1
    return result


def cmd_promote(args: argparse.Namespace) -> Dict[str, Any]:
    return promote.run(repo_root(), args.request, args.dry_run)


def cmd_target_list(args: argparse.Namespace) -> Dict[str, Any]:
    found = targets.load(repo_root())
    return {
        "configured": found.configured,
        "repos": [targets.summary(found.repos[name], found.timeout) for name in found.names()],
        "problems": found.problems,
    }


def cmd_target_show(args: argparse.Namespace) -> Dict[str, Any]:
    found = targets.load(repo_root())
    return targets.summary(found.get(args.repo), found.timeout)


def register(subparsers: Any) -> None:
    request = subparsers.add_parser("request", help="the L3 request")
    commands = request.add_subparsers(dest="request_command", required=True)

    new = commands.add_parser("new", help="create a request and put the session into L3")
    new.add_argument("--title", required=True)
    new.add_argument("--session-id", required=True, help="the session id written at the top of the prompt rules")
    new.add_argument("--surface", default="vscode", choices=["vscode", "cli"])
    new.add_argument("--task", default="", help="the task folder under .workspace/current_tasks/ (promote backs the result up to its DEV folder)")
    new.add_argument("--branch", default="", help="feature/<name> for the target repositories (letters, digits, `_`); can be set later")
    new.set_defaults(handler=cmd_new)

    set_branch = commands.add_parser("set-branch", help="set the feature branch name of a request with target repositories")
    _request(set_branch)
    set_branch.add_argument("--branch", required=True)
    set_branch.set_defaults(handler=cmd_set_branch)

    add = commands.add_parser("add-input", help="copy files into init-inputs/")
    _request(add)
    add.add_argument("paths", nargs="*")
    add.add_argument("--from-target", action="append", default=[], help="<repo>/<path>: a file or folder as the target repository's base branch has it (repeatable)")
    add.set_defaults(handler=cmd_add_input)

    status = commands.add_parser("set-status", help="end the request: accepted, hitl or abandoned")
    _request(status)
    status.add_argument("--status", required=True, choices=["accepted", "hitl", "abandoned"])
    status.add_argument("--reason", default="")
    status.set_defaults(handler=cmd_set_status)

    wait_parser = commands.add_parser("wait", help="say the request is waiting for a person, so the agent may end its turn")
    _request(wait_parser)
    wait_parser.add_argument("--reason", required=True, help="what it waits for, e.g. the person's approval of the promote plan")
    wait_parser.set_defaults(handler=cmd_wait)

    approve = commands.add_parser("approve-promote", help="the person approves the plan of the last promote --dry-run (terminal only)")
    approve.add_argument("--request", default="", help="request id; left out, the only request waiting for approval is used")
    approve.set_defaults(handler=cmd_approve_promote)

    recover = commands.add_parser("recover", help="the person puts the repositories back after a promote stopped halfway (terminal only)")
    recover.add_argument("--request", default="", help="request id; left out, the only request whose promote stopped halfway is used")
    recover.set_defaults(handler=cmd_recover)

    list_parser = commands.add_parser("list", help="list requests, newest first (id, title, status, waiting for approval)")
    list_parser.add_argument("--status", default="", choices=["", "open", "accepted", "hitl", "abandoned"])
    list_parser.set_defaults(handler=cmd_list)

    show = commands.add_parser("show", help="print request.json")
    _request(show)
    show.set_defaults(handler=cmd_show)

    report_parser = subparsers.add_parser("report", help="write .workspace/reports/<request id>.md: result, attempts, handoffs, refusals")
    report_parser.add_argument("--request", default="", help="request id; left out, the newest request is used")
    report_parser.set_defaults(handler=cmd_report)

    brief = subparsers.add_parser("brief", help="the knowledge brief")
    brief_commands = brief.add_subparsers(dest="brief_command", required=True)
    brief_set = brief_commands.add_parser("set", help="validate a brief file and store it as the new version")
    _request(brief_set)
    brief_set.add_argument("file")
    brief_set.set_defaults(handler=cmd_brief_set)

    attempt = subparsers.add_parser("attempt", help="attempts of a request")
    attempt_commands = attempt.add_subparsers(dest="attempt_command", required=True)
    attempt_new = attempt_commands.add_parser("new", help="open the next attempt")
    _request(attempt_new)
    attempt_new.add_argument("--human-approved", default="", help="needed past the attempt limit: why the person agreed")
    attempt_new.set_defaults(handler=cmd_attempt_new)

    dispatch = subparsers.add_parser("dispatch", help="build and freeze the input package of one role")
    _request(dispatch)
    dispatch.add_argument("--role", required=True, choices=["builder", "reviewer"])
    dispatch.add_argument("--input", action="append", default=[], help="a repo file or folder to copy into the package (repeatable)")
    dispatch.add_argument("--from-target", action="append", default=[], help="<repo>/<path> from a target repository's base branch (repeatable)")
    dispatch.set_defaults(handler=cmd_dispatch)

    handoff = subparsers.add_parser("handoff", help="handoffs")
    handoff_commands = handoff.add_subparsers(dest="handoff_command", required=True)
    submit = handoff_commands.add_parser("submit", help="write the handoff of this attempt")
    _request(submit)
    submit.add_argument("--role", required=True, choices=["builder", "reviewer"])
    submit.add_argument("--status", required=True, choices=["passed", "failed", "blocked"])
    submit.add_argument("--summary", required=True)
    submit.add_argument("--output", action="append", default=[], help="a result file, relative to your outputs folder (repeatable)")
    submit.add_argument("--evidence", action="append", default=[], help="an evidence file, relative to your outputs folder (repeatable)")
    submit.add_argument("--blocker", action="append", default=[], help="why it failed or is blocked (repeatable)")
    submit.add_argument("--next", default="")
    submit.add_argument("--kb-addition", action="append", default=[], help="`source :: one-sentence finding` (repeatable)")
    submit.set_defaults(handler=cmd_handoff_submit)

    check_parser = subparsers.add_parser("check", help="does the request folder agree with itself")
    _request(check_parser)
    check_parser.add_argument("--require-conclusion", action="store_true", help="also fail when the request has no conclusion yet")
    check_parser.set_defaults(handler=cmd_check)

    promote_parser = subparsers.add_parser("promote", help="copy the reviewed result into the repository")
    _request(promote_parser)
    promote_parser.add_argument("--dry-run", action="store_true")
    promote_parser.set_defaults(handler=cmd_promote)

    target = subparsers.add_parser("target", help="the target repositories")
    target_commands = target.add_subparsers(dest="target_command", required=True)
    target_list = target_commands.add_parser("list", help="every target repository: path, base branch, its commit, clean or not")
    target_list.set_defaults(handler=cmd_target_list)
    target_show = target_commands.add_parser("show", help="one target repository")
    target_show.add_argument("--repo", required=True, help="the repository name (the folder name under repos_root)")
    target_show.set_defaults(handler=cmd_target_show)
