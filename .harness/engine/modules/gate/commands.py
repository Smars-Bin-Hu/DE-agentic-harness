"""CLI command of the gate module.

  approve-command    the person approves one git command the gate refused (terminal only)
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Dict, Optional

from core import config
from core.paths import repo_root

from . import approvals
from .policy import POLICY_NAME


class CommandError(Exception):
    """A refused command. The message says why and what to do next."""


def approve(
    root: Any,
    reader: Optional[Callable[[str], str]] = None,
    interactive: Optional[bool] = None,
    out: Any = None,
) -> Dict[str, Any]:
    """Show the git commands waiting for a person, then approve the one whose code is typed. Terminal only, like `approve-promote`."""
    out = out or sys.stdout
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        raise CommandError("approve-command 只能由用户在自己的终端里手动运行，要打字确认。agent 不能运行它，管道和脚本也不行。")
    minutes = approvals.minutes(config.load_policy(root, POLICY_NAME))
    waiting = approvals.pending(root, minutes)
    if not waiting:
        raise CommandError(f"没有等待批准的 git 命令（{minutes} 分钟内）。让 agent 先运行那条命令，被拒绝后再来。")
    print("这些 git 命令在等你批准。批准后，同一个会话里同一条命令 %d 分钟内可以运行一次：" % minutes, file=out)
    for number, item in enumerate(waiting, 1):
        print(f"  [{number}] 会话 {item['session_id']}（{item['surface']}），{item['created_at']}", file=out)
        print(f"      {item['command']}", file=out)
    answer = (reader or input)("输入 agent 给你的验证码来批准其中一条（其他任何输入都是取消）：").strip()
    done = approvals.approve(root, answer, minutes) if answer else None
    if done is None:
        raise CommandError("没有批准。什么都没有运行。")
    return {"approved": True, "command": done["command"], "valid_minutes": minutes, "next": "告诉 agent 可以再运行这条命令了（写法要完全一样）。"}


def cmd_approve_command(args: Any) -> Dict[str, Any]:
    return approve(repo_root())


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("approve-command", help="the person approves a git command the gate refused (terminal only)")
    parser.set_defaults(handler=cmd_approve_command)
