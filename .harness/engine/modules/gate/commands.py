"""CLI commands of the gate module.

  approve-command    the person approves one git command the gate refused (terminal only)
  admin on           the person switches admin mode on for one session (terminal only): guardrail files open up for it
  admin off          switch it off again (anyone may: it only takes rights away)
  admin status       the sessions that are in admin mode
"""

from __future__ import annotations

import sys
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import approval, config, guardrails, tasks
from core.paths import cli_command, repo_root, state_dir, utc_now
from core.state import admin_on, session, state_path

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


SURFACES = ("vscode", "cli")


def _known_session(root: Path, surface: str, session_id: str) -> None:
    if not state_path(root, surface, session_id).exists():
        raise CommandError(f"没有会话 `{session_id}`。会话 id 写在 agent 每条提示开头的规则里，让 agent 原样给你。")


def admin_switch_on(
    root: Path,
    session_id: str,
    surface: str = "vscode",
    reader: Optional[Callable[[str], str]] = None,
    interactive: Optional[bool] = None,
    out: Any = None,
) -> Dict[str, Any]:
    """Admin mode for one session. Terminal only, with a typed code, like `approve-plan`: a hook cannot tell which agent
    is talking, so choosing the admin agent in the picker cannot be what opens the guardrail files."""
    try:
        approval.require_person("admin on", interactive)
    except approval.Refused as error:
        raise CommandError(str(error)) from error
    _known_session(root, surface, session_id)
    locked = guardrails.admin_locked(config.load_policy(root, POLICY_NAME))
    with session(root, surface, session_id) as state:
        if state.get("parent_session_id"):
            raise CommandError("这是一个子 agent 的会话。admin 不能是子 agent。")
        if state["active_request"]:
            raise CommandError(f"这个会话有进行中的 L3 请求 `{state['active_request']}`。admin 模式不和任务混用：换一个新对话再开。")
        if tasks.open_of(root, state) is not None:
            raise CommandError(f"这个会话在做任务 `{state.get('active_task')}`。admin 模式不和任务混用：换一个新对话再开。")
        if admin_on(state):
            return {"admin": True, "session_id": session_id, "note": "这个会话已经在 admin 模式里。"}
        approval.say(
            out,
            f"会话 {session_id}（{surface}）将进入 admin 模式，直到你运行 `admin off`：",
            "  这个会话里的 agent 可以改 harness 的 guardrail 文件（hook 配置、策略、engine、短命令、registry、.vscode/settings.json）。",
            f"  仍然不能改：{'、'.join(locked)}、CLI 生成的文件、.git、目标仓库。批准类命令仍然只有你能运行。",
            "  Task Level 的预算不再限制它。只在你要二开或排查 harness 时开，用完就关。",
        )
        try:
            approval.ask("确认开启", hashlib.sha256(f"admin\n{surface}\n{session_id}".encode("utf-8")).hexdigest(), "没有开启。什么都没有改。", reader)
        except approval.Refused as error:
            raise CommandError(str(error)) from error
        state["admin"] = {"on": True, "at": utc_now()}
    return {"admin": True, "session_id": session_id, "locked": locked, "next": f"告诉 agent 可以继续了。用完后运行 `{cli_command()} admin off --session-id {session_id}`。"}


def admin_switch_off(root: Path, session_id: str, surface: str = "vscode") -> Dict[str, Any]:
    _known_session(root, surface, session_id)
    with session(root, surface, session_id) as state:
        was = admin_on(state)
        if "admin" in state:
            state["admin"] = {"on": False, "at": utc_now()}
    return {"admin": False, "session_id": session_id, "was_on": was}


def admin_sessions(root: Path) -> List[Dict[str, Any]]:
    """Every session that is in admin mode now, newest first. A state file that cannot be read is skipped."""
    found: List[Dict[str, Any]] = []
    for surface in SURFACES:
        directory = state_dir(root, surface)
        for path in directory.glob("*.json") if directory.is_dir() else ():
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(state, dict) and admin_on(state):
                found.append({"surface": surface, "session_id": state.get("session_id", path.stem), "since": state["admin"].get("at", ""), "updated_at": state.get("updated_at", "")})
    return sorted(found, key=lambda item: item["updated_at"], reverse=True)


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("approve-command", help="the person approves a git command the gate refused (terminal only)")
    parser.set_defaults(handler=cmd_approve_command)

    admin = subparsers.add_parser("admin", help="admin mode of a session: it may change guardrail files")
    commands = admin.add_subparsers(dest="admin_command", required=True)
    on = commands.add_parser("on", help="the person switches admin mode on for one session (terminal only)")
    off = commands.add_parser("off", help="switch admin mode off for one session")
    for item in (on, off):
        item.add_argument("--surface", default="vscode", choices=list(SURFACES))
        item.add_argument("--session-id", required=True)
    on.set_defaults(handler=lambda args: admin_switch_on(repo_root(), args.session_id, args.surface))
    off.set_defaults(handler=lambda args: admin_switch_off(repo_root(), args.session_id, args.surface))
    status = commands.add_parser("status", help="the sessions that are in admin mode")
    status.set_defaults(handler=lambda args: {"admin_sessions": admin_sessions(repo_root())})
