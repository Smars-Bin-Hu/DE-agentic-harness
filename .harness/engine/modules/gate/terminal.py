"""Terminal commands: what writes a guardrail file, what is denied, what needs a person to confirm.

Reads (`cat`, `rg`, `ls`, `git diff`) match nothing here. A command that matches nothing is allowed, and the
runtime's own terminal confirmation still applies. This is a net for common cases, not a sandbox: a command can write
any path in ways a regular expression does not see.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .policy import Compiled

# (permission, why)
Verdict = Tuple[str, str]


_SEPARATORS = ";&|(\n"


def normalize(command: str) -> str:
    """One spelling for paths in a command (`\\` becomes `/`), and quoted text cannot start a new command.

    `rg "rm -rf|git checkout" src` has a `|` inside quotes. It is not a pipe, so it is turned into a space.
    A quote that never closes is left alone.
    """
    text = command.replace("\\", "/")
    out = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in "\"'":
            end = text.find(char, index + 1)
            if end != -1:
                inner = "".join(" " if item in _SEPARATORS else item for item in text[index + 1:end])
                out.append(char + inner + char)
                index = end + 1
                continue
        out.append(char)
        index += 1
    return "".join(out)


def guardrail_write(command: str, compiled: Compiled) -> Optional[str]:
    """Why this command changes a guardrail file, or None."""
    text = normalize(command)
    for regex, why in compiled.guard_writes:
        if regex.search(text):
            return why
    return None


def owned_write(command: str, compiled: Compiled) -> Optional[str]:
    """Why this command changes a file only the CLI writes, or None."""
    text = normalize(command)
    for regex, why in compiled.owned_writes:
        if regex.search(text):
            return why
    return None


def git_write(command: str, compiled: Compiled) -> Optional[str]:
    """Why this command changes a `.git` folder or a path a target repository refuses, or None."""
    text = normalize(command)
    for regex, why in compiled.target_writes:
        if regex.search(text):
            return why
    return None


def tree_write(command: str, compiled: Compiled) -> Optional[str]:
    """Why this command writes into the working tree of a target repository (named by its full path), or None."""
    text = normalize(command)
    for regex, why in compiled.tree_writes:
        if regex.search(text):
            return why
    return None


def check(command: str, compiled: Compiled) -> Optional[Verdict]:
    """`("deny", why)`, `("ask", why)` or None. Deny rules come first."""
    if not command.strip():
        return None
    text = normalize(command)
    for regex, why in compiled.deny:
        if regex.search(text):
            return "deny", why
    for regex, why in compiled.ask:
        if regex.search(text):
            return "ask", why
    return None
