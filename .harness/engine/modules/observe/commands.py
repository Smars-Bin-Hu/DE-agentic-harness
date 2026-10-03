"""CLI commands of the observe module.

  stats                numbers from the session logs: prompts per Level, refusals, verifier verdicts, hook time
  logs prune           delete session logs not written to for N days (a person decides; no hook deletes anything)
"""

from __future__ import annotations

import argparse
from typing import Any, Dict

from core.paths import repo_root

from . import prune, stats


def cmd_stats(args: argparse.Namespace) -> Dict[str, Any]:
    return stats.collect(repo_root(), args.session_id, args.surface, args.days)


def cmd_prune(args: argparse.Namespace) -> Dict[str, Any]:
    return prune.prune(repo_root(), args.days, args.dry_run)


def register(subparsers: Any) -> None:
    stats_parser = subparsers.add_parser("stats", help="counts and times from the session logs")
    stats_parser.add_argument("--session-id", default="", help="only this session")
    stats_parser.add_argument("--surface", default="", choices=["", "vscode", "cli"])
    stats_parser.add_argument("--days", type=int, default=None, help="only the calls of the last N days")
    stats_parser.set_defaults(handler=cmd_stats)

    logs = subparsers.add_parser("logs", help="the session logs")
    commands = logs.add_subparsers(dest="logs_command", required=True)
    prune_parser = commands.add_parser("prune", help="delete session logs not written to for N days")
    prune_parser.add_argument("--days", type=int, required=True)
    prune_parser.add_argument("--dry-run", action="store_true", help="list what would be deleted")
    prune_parser.set_defaults(handler=cmd_prune)
