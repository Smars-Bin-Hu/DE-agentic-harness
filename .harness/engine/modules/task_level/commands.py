"""CLI commands for task_level: `cli.py level status|begin|set|complete`."""

from __future__ import annotations

import argparse
from typing import Any, Dict

from core import config
from core.paths import repo_root
from core.state import session, update_state

from . import lifecycle
from .handler import NAME
from .policy import POLICY_NAME, validate_policy


def _mutate(args: argparse.Namespace, action: Any) -> Dict[str, Any]:
    root = repo_root()

    def mutator(state: Dict[str, Any]) -> None:
        ms = lifecycle.ensure_module_state(state, NAME)
        action(ms)
        lifecycle.sync_shared_level(state, ms)

    return update_state(root, args.surface, args.session_id, mutator)


def cmd_status(args: argparse.Namespace) -> Dict[str, Any]:
    with session(repo_root(), args.surface, args.session_id) as state:
        lifecycle.ensure_module_state(state, NAME)
    return state


def cmd_begin(args: argparse.Namespace) -> Dict[str, Any]:
    return _mutate(args, lambda ms: lifecycle.begin_task(ms, args.reason, args.replace))


def cmd_set(args: argparse.Namespace) -> Dict[str, Any]:
    policy = config.load_policy(repo_root(), POLICY_NAME)
    validate_policy(policy)
    return _mutate(args, lambda ms: lifecycle.set_level(ms, args.level, args.reason, policy))


def cmd_complete(args: argparse.Namespace) -> Dict[str, Any]:
    return _mutate(args, lambda ms: lifecycle.complete_task(ms, args.reason))


def _session_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--surface", default="vscode", choices=["vscode", "cli"])
    parser.add_argument("--session-id", required=True)


def register(subparsers: Any) -> None:
    level = subparsers.add_parser("level", help="task level state of a session")
    commands = level.add_subparsers(dest="level_command", required=True)

    status = commands.add_parser("status", help="show the session state")
    _session_arguments(status)
    status.set_defaults(handler=cmd_status)

    begin = commands.add_parser("begin", help="begin a Level 1 task")
    _session_arguments(begin)
    begin.add_argument("--reason", required=True)
    begin.add_argument("--replace", action="store_true")
    begin.set_defaults(handler=cmd_begin)

    set_command = commands.add_parser("set", help="change the level of the active task")
    _session_arguments(set_command)
    set_command.add_argument("--level", required=True, type=int)
    set_command.add_argument("--reason", required=True)
    set_command.set_defaults(handler=cmd_set)

    complete = commands.add_parser("complete", help="complete the active task")
    _session_arguments(complete)
    complete.add_argument("--reason", required=True)
    complete.set_defaults(handler=cmd_complete)
