#!/usr/bin/env python3
"""Command line entry for agents and people: <python> .harness/engine/cli.py <command> (python on Windows, python3 elsewhere).

  doctor                       check that the harness files and config are consistent
  user                         the name of the person using this copy (for a change note that needs an author)
  level status|set             level of a session (task_level module)
  request, brief, attempt, dispatch, handoff, check, promote   the L3 request (request module)
  target list|show             the target repositories (request module)
  approve-command              a person approves a git command the gate refused (gate module)
  admin on|off|status          a person switches admin mode on for one session: it may then change guardrail files (gate module)
  stats, logs prune            numbers from the session logs; delete old logs (observe module)
  eval list|show|check         fixed scenarios, judged from a finished run (evalcheck module)
  --version [--short]          the harness release, date and authors (from .harness/registry.json); --short prints one line
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import output, user  # noqa: E402
from core.paths import repo_root  # noqa: E402
from core.registry import harness_version, version_banner  # noqa: E402
import doctor  # noqa: E402
from modules.evalcheck import commands as eval_commands  # noqa: E402
from modules.gate import commands as gate_commands  # noqa: E402
from modules.observe import commands as observe_commands  # noqa: E402
from modules.request import commands as request_commands  # noqa: E402
from modules.task_level import commands as task_level_commands  # noqa: E402


SHORT_FLAG = "--short"
ARGV = None  # the arguments main() was called with, when it was not the command line


class ShowVersion(argparse.Action):
    """`--version` reads the registry only when it is asked for: a broken registry must not break the other commands (doctor reports it)."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, help="show the harness version and exit")

    def __call__(self, parser, namespace, values, option_string=None):
        try:
            if SHORT_FLAG in (ARGV if ARGV is not None else sys.argv[1:]):
                print(f"harness {harness_version(repo_root())}")  # one line, for scripts
            else:
                print(version_banner(repo_root()))
        except Exception as error:
            print(f"harness: 读不到版本号：{error}", file=sys.stderr)
            parser.exit(1)
        parser.exit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="Harness CLI")
    parser.add_argument("--version", action=ShowVersion)
    parser.add_argument(SHORT_FLAG, action="store_true", help="with --version: only `harness <version>`, one line")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor", help="check harness files and config")
    check.set_defaults(handler=None)
    name = commands.add_parser("user", help="the name of the person using this copy (user.override.json, else git config user.name)")
    name.set_defaults(handler=lambda _args: user.who(repo_root()))
    task_level_commands.register(commands)
    request_commands.register(commands)
    gate_commands.register(commands)
    observe_commands.register(commands)
    eval_commands.register(commands)
    return parser


def safe_streams() -> None:
    """A character the terminal encoding cannot show (a Chinese text on a Windows pipe) must not kill the command.

    It is printed as \\uXXXX. `output.encoding: utf-8` in the cli policy prints UTF-8 instead, for a reader that decodes UTF-8.
    """
    encoding = output.configured_encoding()
    for stream in (sys.stdout, sys.stderr):
        try:
            if encoding:
                stream.reconfigure(encoding=encoding, errors="backslashreplace")
            else:
                stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, LookupError):
            pass


def main(argv=None) -> int:
    global ARGV
    ARGV = argv
    safe_streams()
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor.run(repo_root())
    try:
        result = args.handler(args)
        code = result.pop("exit_code", 0) if isinstance(result, dict) else 0
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return code
    except Exception as error:
        print(f"harness: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
