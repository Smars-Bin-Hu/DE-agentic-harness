#!/usr/bin/env python3
"""Command line entry for agents and people: python3 .harness/engine/cli.py <command>.

  doctor                       check that the harness files and config are consistent
  level status|set             level of a session (task_level module)
  request, brief, attempt, dispatch, handoff, check, promote   the L3 request (request module)
  stats, logs prune            numbers from the session logs; delete old logs (observe module)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.paths import repo_root  # noqa: E402
import doctor  # noqa: E402
from modules.observe import commands as observe_commands  # noqa: E402
from modules.request import commands as request_commands  # noqa: E402
from modules.task_level import commands as task_level_commands  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Harness CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor", help="check harness files and config")
    check.set_defaults(handler=None)
    task_level_commands.register(commands)
    request_commands.register(commands)
    observe_commands.register(commands)
    return parser


def main(argv=None) -> int:
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
