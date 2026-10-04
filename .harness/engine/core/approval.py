"""A person's approval at a terminal: the one mechanism behind approve-plan, approve-promote and recover.

A tool-call dialog cannot be the guard ("Allow in this Session" switches it off), so the approval needs a terminal the
person types in (stdin and stdout are a TTY) and a code that is bound to what is approved (the first characters of a
sha256). The gate also denies an agent that tries to run these commands.

The screen stays short on purpose: it names the file to read in the editor and never prints the content itself.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Optional

CODE_LENGTH = 8


class Refused(Exception):
    """Not approved. The message says why and what to do next."""


def code_of(digest: str) -> str:
    return digest[:CODE_LENGTH]


def require_person(command: str, interactive: Optional[bool] = None) -> None:
    """`interactive` exists so tests can stand in for a person; the CLI passes None."""
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        raise Refused(f"{command} 只能由用户在自己的终端里手动运行，要打字确认。agent 不能运行它，管道和脚本也不行。")


def ask(question: str, digest: str, refusal: str, reader: Optional[Callable[[str], str]] = None) -> None:
    """Ask the person to type the code of `digest`. Anything else raises Refused(refusal)."""
    code = code_of(digest)
    answer = (reader or input)(f"{question}，输入 {code}（其他任何输入都是取消）：").strip()
    if answer != code:
        raise Refused(refusal)


def say(out: Any, *lines: str) -> None:
    for line in lines:
        print(line, file=out or sys.stdout)
