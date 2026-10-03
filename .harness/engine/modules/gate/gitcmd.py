"""git commands in a terminal call: what only reads, what needs a person's approval, what is never approved (A5).

An agent may read with git. Anything else changes a repository, so a person approves that exact command (`approve-command`).
Some commands are never approved: they publish, or throw away history and work (`push`, `clean`, `reset --hard`, `branch -D`,
any force). A command that is not clearly a read is treated as a write; the person sees the whole command before approving.

The splitting is quote-aware but it is not a shell parser. A command it cannot see into (a `$VAR` for the sub-command, an
alias) is a write. A script that runs git in a way no pattern sees is not caught: this is a net, not a sandbox.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

NONE, APPROVE, NEVER = "none", "approve", "never"
MAX_DEPTH = 3

READ_ONLY = frozenset(
    "status diff log show blame annotate rev-parse rev-list ls-files ls-tree cat-file describe shortlog grep show-ref "
    "for-each-ref name-rev merge-base diff-tree diff-files diff-index check-ignore check-attr count-objects version help "
    "whatchanged cherry range-diff show-branch verify-commit verify-tag var".split()
)
NEVER_SUBCOMMANDS = {
    "push": "它会把提交发到远程仓库",
    "clean": "它会删除没有跟踪的文件",
    "filter-branch": "它会改写整个历史",
    "filter-repo": "它会改写整个历史",
    "update-ref": "它会直接移动分支或删除引用",
    "prune": "它会永久删除没有引用的对象",
}
# Subcommands where a lone `-f` means force. (`git tag -F`, `git config -f <file>` mean something else.)
FORCE_SHORT = frozenset("add checkout switch branch tag mv rm fetch pull worktree submodule clean push".split())
# Words that may stand before `git` without hiding it.
WRAPPERS = frozenset("sudo env nohup time command exec nice timeout xargs call start watch".split())
SHELLS = frozenset("bash sh zsh dash fish pwsh powershell cmd".split())
SHELL_FLAGS = frozenset(["-c", "-command", "/c", "-lc", "-ic", "-encodedcommand"])
SCRIPT_RUNNERS = frozenset("python python3 py node perl ruby".split())
SCRIPT_FLAGS = frozenset(["-c", "-e", "-r"])
OPTIONS_WITH_VALUE = frozenset(["-c", "-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env", "--exec-path", "--attr-source"])
CONFIG_OPTIONS = ("-c", "--config-env", "--exec-path")
SEPARATORS = ";&|()`\n"


@dataclass
class Verdict:
    kind: str = NONE
    why: str = ""
    commands: List[str] = field(default_factory=list)  # the git commands found, one per line, for the person to read


def collapse(command: str) -> str:
    """One spelling of a command for comparing: runs of white space become one space."""
    return " ".join(command.split())


def split_segments(text: str) -> List[List[str]]:
    """The commands of a command line, each as tokens with their quotes removed. Quote-aware: `;` inside quotes splits nothing."""
    segments: List[List[str]] = [[]]
    token: Optional[str] = None
    quote = ""
    index = 0

    def end_token() -> None:
        nonlocal token
        if token is not None:
            segments[-1].append(token)
            token = None

    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
            else:
                token = (token or "") + char
        elif char in "\"'":
            quote = char
            token = token or ""
        elif char in SEPARATORS:
            end_token()
            if segments[-1]:
                segments.append([])
        elif char.isspace():
            end_token()
        else:
            token = (token or "") + char
        index += 1
    end_token()
    return [item for item in segments if item]


def _name(token: str) -> str:
    """`/usr/bin/git`, `C:\\Program Files\\Git\\cmd\\git.exe` and `git.exe` are all `git`."""
    base = posixpath.basename(token.replace("\\", "/")).lower()
    return base[:-4] if base.endswith(".exe") else base


def _is_environment(token: str) -> bool:
    return bool(re.match(r"^[A-Za-z_]\w*=", token))


def _git_start(tokens: List[str], name: str) -> Optional[int]:
    """Index of the program `name` when only wrappers, environment settings and numbers stand before it."""
    for index, token in enumerate(tokens):
        if _name(token) == name:
            return index
        if not (_name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit()):
            return None
    return None


def _flags(arguments: List[str]) -> List[str]:
    return [item for item in arguments if item.startswith("-")]


def _positional(arguments: List[str]) -> List[str]:
    return [item for item in arguments if not item.startswith("-")]


def _force(subcommand: str, arguments: List[str]) -> bool:
    for item in arguments:
        if item in ("--force", "--discard-changes") or item.startswith(("--force=", "--force-with-lease", "--force-if-includes")):
            return True
        if subcommand in FORCE_SHORT and re.match(r"^-[A-Za-z]*f[A-Za-z]*$", item):
            return True
    return False


def _reads(subcommand: str, arguments: List[str]) -> bool:
    """Whether a command that is only sometimes a read is a read here."""
    flags, words = _flags(arguments), _positional(arguments)
    first = words[0].lower() if words else ""
    if subcommand == "branch":
        lists = any(item in ("-l", "--list") for item in flags)
        changes = any(item in ("-d", "-D", "-m", "-M", "-c", "-C", "-u", "-f", "--delete", "--move", "--copy", "--force", "--unset-upstream", "--edit-description") or item.startswith("--set-upstream") for item in flags)
        return not changes and (lists or not words)
    if subcommand == "tag":
        lists = any(item in ("-l", "--list", "-n") or item.startswith(("--contains", "--points-at", "--merged", "--no-merged", "--sort")) for item in flags)
        changes = any(item in ("-d", "-a", "-s", "-u", "-m", "-F", "-f", "--delete", "--force") for item in flags)
        return not changes and (lists or not words)
    if subcommand == "stash":
        return first in ("list", "show")
    if subcommand == "remote":
        return first in ("", "show", "get-url") and not any(item in ("add", "remove", "rename") for item in words)
    if subcommand == "config":
        return any(item in ("--get", "--get-all", "--get-regexp", "--list", "-l", "--get-urlmatch", "--show-origin", "--show-scope") for item in flags)
    if subcommand == "worktree":
        return first == "list"
    if subcommand == "reflog":
        return first in ("", "show", "exists")
    if subcommand == "submodule":
        return first in ("status", "summary")
    return subcommand in READ_ONLY


def _git(tokens: List[str], start: int) -> Tuple[str, str]:
    """`(kind, why)` of one git command. `tokens[start]` is the program."""
    environment = [item for item in tokens[:start] if _is_environment(item) and item.upper().startswith("GIT_")]
    rest = tokens[start + 1:]
    exotic = bool(environment)
    index = 0
    while index < len(rest) and rest[index].startswith("-"):
        option = rest[index]
        if option in CONFIG_OPTIONS or option.startswith(("--config-env=", "--exec-path=")):
            exotic = True
        index += 2 if option in OPTIONS_WITH_VALUE else 1
    if index >= len(rest):
        return NONE, ""  # `git`, `git --version`, `git --help`
    subcommand, arguments = rest[index].lower(), rest[index + 1:]
    if re.search(r"[$%]|^\W", subcommand):
        return APPROVE, "git 的子命令看不清楚"
    if subcommand in NEVER_SUBCOMMANDS:
        return NEVER, f"`git {subcommand}`：{NEVER_SUBCOMMANDS[subcommand]}"
    if subcommand == "reset" and any(item == "--hard" for item in arguments):
        return NEVER, "`git reset --hard`：它会丢掉没有提交的改动"
    if subcommand == "gc" and any(item.startswith("--prune") for item in arguments):
        return NEVER, "`git gc --prune`：它会永久删除没有引用的对象"
    if subcommand == "reflog" and _positional(arguments)[:1] in (["expire"], ["delete"]):
        return NEVER, "`git reflog expire/delete`：它会丢掉恢复用的记录"
    if subcommand == "branch" and any(item == "-D" for item in arguments):
        return NEVER, "`git branch -D`：它会强制删除分支"
    if _force(subcommand, arguments):
        return NEVER, f"`git {subcommand}` 带了强制选项（--force、-f）"
    if exotic or any(item.startswith("--output") or item == "-o" for item in arguments if subcommand in READ_ONLY):
        return APPROVE, "它带了会改配置或写文件的选项"
    if subcommand == "grep" and any(item.startswith(("-O", "--open-files-in-pager")) for item in arguments):
        return APPROVE, "`git grep -O` 会运行别的程序"
    if _reads(subcommand, arguments):
        return NONE, ""
    return APPROVE, f"`git {subcommand}` 会改仓库"


def _gh(tokens: List[str], start: int) -> Tuple[str, str]:
    words = _positional(tokens[start + 1:])
    if words and words[0].lower() == "pr":
        return NEVER, "`gh pr`：它会在远程创建或改动 pull request"
    return NONE, ""


def _scan(text: str, depth: int, found: List[Tuple[str, str, str]]) -> None:
    for tokens in split_segments(text):
        line = " ".join(tokens)
        start = _git_start(tokens, "git")
        if start is not None:
            kind, why = _git(tokens, start)
            if kind != NONE:
                found.append((kind, why, line))
            continue
        start = _git_start(tokens, "gh")
        if start is not None:
            kind, why = _gh(tokens, start)
            if kind != NONE:
                found.append((kind, why, line))
            continue
        if not tokens:
            continue
        program = next((_name(item) for item in tokens if not (_name(item) in WRAPPERS or _is_environment(item) or item.startswith("-"))), "")
        shell_at = next((i for i, item in enumerate(tokens) if _name(item) in SHELLS), None)
        if shell_at is not None and depth < MAX_DEPTH:
            for i in range(shell_at + 1, len(tokens)):
                if tokens[i].lower() in SHELL_FLAGS and i + 1 < len(tokens):
                    _scan(" ".join(tokens[i + 1:]) if len(tokens) > i + 2 else tokens[i + 1], depth + 1, found)
                    break
        elif program in SCRIPT_RUNNERS and any(item in SCRIPT_FLAGS for item in tokens) and re.search(r"\bgit\b", line):
            found.append((APPROVE, "内联脚本里有 git", line))


def classify(command: str) -> Verdict:
    """What the git commands in this command line need. `never` wins over `approve`; no git write at all is `none`."""
    found: List[Tuple[str, str, str]] = []
    _scan(command, 0, found)
    if not found:
        return Verdict()
    never = [item for item in found if item[0] == NEVER]
    pick = never or found
    return Verdict(NEVER if never else APPROVE, "；".join(dict.fromkeys(item[1] for item in pick)), [item[2] for item in found])
