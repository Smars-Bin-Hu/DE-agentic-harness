"""CLI commands for task_level, for people debugging a session: `cli.py level status|set`.

An agent running `level set` is denied by the PreToolUse hook. The user can run it in their own terminal.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict

from core import config
from core.paths import repo_root
from core.state import session, update_state

from . import levelstate
from .handler import NAME
from .policy import POLICY_NAME, validate_policy


def cmd_status(args: argparse.Namespace) -> Dict[str, Any]:
    with session(repo_root(), args.surface, args.session_id) as state:
        levelstate.ensure_module_state(state, NAME)
    return state


def cmd_set(args: argparse.Namespace) -> Dict[str, Any]:
    root = repo_root()
    validate_policy(config.load_policy(root, POLICY_NAME))

    def mutator(state: Dict[str, Any]) -> None:
        if state["active_request"]:
            raise ValueError("An L3 request is running. Its level cannot be changed from here.")
        levelstate.set_level(state, levelstate.ensure_module_state(state, NAME), args.level, "cli")

    return update_state(root, args.surface, args.session_id, mutator)


def _session_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--surface", default="vscode", choices=["vscode", "cli"])
    parser.add_argument("--session-id", required=True)


def register(subparsers: Any) -> None:
    level = subparsers.add_parser("level", help="level of a session")
    commands = level.add_subparsers(dest="level_command", required=True)

    status = commands.add_parser("status", help="show the session state")
    _session_arguments(status)
    status.set_defaults(handler=cmd_status)

    set_command = commands.add_parser("set", help="set the level (1 or 2). For the user, not for agents")
    _session_arguments(set_command)
    set_command.add_argument("--level", required=True, type=int)
    set_command.set_defaults(handler=cmd_set)
