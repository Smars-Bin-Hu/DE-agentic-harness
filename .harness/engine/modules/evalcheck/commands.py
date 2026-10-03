"""CLI commands of the evalcheck module.

  eval list                          the fixed scenarios
  eval show <scenario>               the prompt to paste into Copilot, the setup, the manual checks
  eval check <scenario>              judge a finished run: its session log and its request folder
"""

from __future__ import annotations

import argparse
from typing import Any, Dict

from core.paths import repo_root

from . import checks, scenario


def cmd_list(args: argparse.Namespace) -> Dict[str, Any]:
    return {"scenarios": scenario.titles(repo_root())}


def cmd_show(args: argparse.Namespace) -> Dict[str, Any]:
    loaded = scenario.load(repo_root(), args.scenario)
    prompt = scenario.section(loaded["text"], "## Prompt")
    if prompt.startswith("```"):
        prompt = "\n".join(line for line in prompt.splitlines() if not line.startswith("```")).strip()
    return {
        "id": loaded["id"],
        "title": loaded["text"].splitlines()[0].lstrip("# ").strip(),
        "before": scenario.section(loaded["text"], "## 前置"),
        "prompt": prompt,
        "manual_checks": loaded["manual"],
        "then": f"python3 .harness/engine/cli.py eval check {loaded['id']}",
    }


def cmd_check(args: argparse.Namespace) -> Dict[str, Any]:
    root = repo_root()
    result = checks.run(root, scenario.load(root, args.scenario), args.surface, args.session_id, args.request)
    if not result["passed"]:
        result["exit_code"] = 1
    return result


def register(subparsers: Any) -> None:
    evaluate = subparsers.add_parser("eval", help="fixed scenarios, judged from the session log and the request folder")
    commands = evaluate.add_subparsers(dest="eval_command", required=True)
    commands.add_parser("list", help="list the scenarios").set_defaults(handler=cmd_list)
    show = commands.add_parser("show", help="print the prompt of a scenario, ready to paste, and what to do before and after")
    show.add_argument("scenario")
    show.set_defaults(handler=cmd_show)
    check = commands.add_parser("check", help="judge one finished run against a scenario")
    check.add_argument("scenario")
    check.add_argument("--session-id", default="", help="the session of the run; left out, the newest main session is used")
    check.add_argument("--request", default="", help="the request id; left out, the request of that session is used")
    check.add_argument("--surface", default="vscode", choices=["vscode", "cli"])
    check.set_defaults(handler=cmd_check)
