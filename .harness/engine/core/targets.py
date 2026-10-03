"""Target repositories: git repositories outside the harness folder that an L3 request reads from and promotes into.

Policy `target.json` (override: `target.override.json`):
  repos_root  a folder; every subfolder that is a git repository is a target, named after the folder
  repos       name -> {path?, base_ref?, refused_paths?}: a repository elsewhere, or settings for a found one
  base_ref    the branch files are read from (default main)

Everything here reads. Nothing writes to a target repository. git is run with an argument list, never through a shell.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config, repo_paths, schema

POLICY_NAME = "target"
REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
DEFAULT_GIT_TIMEOUT = 30
BRANCH = re.compile(r"^feature/[A-Za-z0-9_]{1,60}$")
REGULAR_FILE_MODES = ("100644", "100755")
LONG_PATH_WARNING = 90  # characters; a request folder and a repository path add about 150 more, Windows stops at 260

_PATHS = {"type": "array", "items": {"type": "string", "minLength": 1}}
POLICY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "repos_root", "repos", "base_ref", "refused_paths"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "repos_root": {"type": "string"},
        "repos": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "base_ref": {"type": "string", "minLength": 1}, "refused_paths": _PATHS},
                "additionalProperties": False,
            },
        },
        "base_ref": {"type": "string", "minLength": 1},
        "refused_paths": _PATHS,
        "git_timeout_seconds": {"type": "integer", "minimum": 1},
    },
}


class TargetError(ValueError):
    """A target repository cannot be found or read."""


@dataclass
class Repo:
    name: str
    path: Path
    base_ref: str
    refused_paths: List[str] = field(default_factory=list)


@dataclass
class Targets:
    configured: bool
    repos: Dict[str, Repo]
    problems: List[str]
    timeout: int = DEFAULT_GIT_TIMEOUT

    def names(self) -> List[str]:
        return sorted(self.repos)

    def get(self, name: str) -> Repo:
        if name not in self.repos:
            known = "、".join(self.names()) or "（没有配置目标仓库）"
            raise TargetError(f"没有叫 `{name}` 的目标仓库。已知的仓库：{known}。")
        return self.repos[name]


def validate_policy(policy: Dict[str, Any]) -> None:
    schema.check(policy, POLICY_SCHEMA, POLICY_NAME + ".json")
    for name in policy["repos"]:
        if not REPO_NAME.match(name):
            raise ValueError(f"Invalid {POLICY_NAME}.json: repo name {name!r} may only hold letters, digits, `_`, `.` and `-`")
    patterns = list(policy["refused_paths"])
    for entry in policy["repos"].values():
        patterns += entry.get("refused_paths", [])
    for pattern in patterns:
        repo_paths.glob_regex(pattern)


def expand(raw: str) -> Path:
    """`~` and environment variables (`%USERPROFILE%`, `$HOME`) in a configured path."""
    return Path(os.path.expandvars(os.path.expanduser(raw.strip())))


def is_repo(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()


def load(root: Path) -> Targets:
    """The configured repositories. Problems (a missing folder, a settings-only entry for an unknown name) are listed, not raised."""
    policy = config.load_policy(root, POLICY_NAME)
    validate_policy(policy)
    timeout = policy.get("git_timeout_seconds", DEFAULT_GIT_TIMEOUT)
    base_ref, refused = policy["base_ref"], list(policy["refused_paths"])
    problems: List[str] = []
    repos: Dict[str, Repo] = {}
    base = policy["repos_root"].strip()
    if base:
        folder = expand(base)
        if not folder.is_dir():
            problems.append(f"repos_root 不存在或不是文件夹：{folder}")
        else:
            for child in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
                if REPO_NAME.match(child.name) and is_repo(child):
                    repos[child.name] = Repo(child.name, child, base_ref, list(refused))
    for name, entry in policy["repos"].items():
        if entry.get("path", "").strip():
            location = expand(entry["path"])
            if not is_repo(location):
                problems.append(f"仓库 {name} 的路径不是 git 仓库：{location}")
                continue
            repos[name] = Repo(name, location, base_ref, list(refused))
        elif name not in repos:
            problems.append(f"repos 里的 {name} 没有 path，repos_root 下也没有这个仓库")
            continue
        repo = repos[name]
        repo.base_ref = entry.get("base_ref", repo.base_ref)
        repo.refused_paths = list(entry.get("refused_paths", repo.refused_paths))
    return Targets(configured=bool(base or policy["repos"]), repos=repos, problems=problems, timeout=timeout)


# --- reading a repository ---------------------------------------------------------------------


def git(repo: Repo, *arguments: str, timeout: int = DEFAULT_GIT_TIMEOUT, allow_failure: bool = False) -> bytes:
    """Run `git -C <repo> ...` and return its stdout as bytes. Raises TargetError on failure unless `allow_failure`."""
    command = ["git", "-C", str(repo.path), "-c", "core.quotepath=off", *arguments]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout, env=env, check=False)
    except (FileNotFoundError, PermissionError) as error:  # PermissionError: PATH is empty and the folder holds a directory called `git`
        raise TargetError("找不到 git 命令。确认 git 在 PATH 里。") from error
    except subprocess.TimeoutExpired as error:
        raise TargetError(f"git {' '.join(arguments)} 超过 {timeout} 秒没有结束（仓库 {repo.name}）。") from error
    if done.returncode != 0 and not allow_failure:
        message = done.stderr.decode("utf-8", errors="replace").strip()
        raise TargetError(f"git {' '.join(arguments)} 失败（仓库 {repo.name}）：{message}")
    return done.stdout if done.returncode == 0 else b""


def run_step(path: Path, arguments: List[str], timeout: int = DEFAULT_GIT_TIMEOUT) -> Tuple[int, str]:
    """`git -C <path> <arguments>` as one step of something a person asked for: (exit code, what git said). Never raises."""
    command = ["git", "-C", str(path), "-c", "core.quotepath=off", *arguments]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout, env=env, check=False)
    except (FileNotFoundError, PermissionError):
        return 127, "找不到 git 命令。确认 git 在 PATH 里。"
    except subprocess.TimeoutExpired:
        return 124, f"超过 {timeout} 秒没有结束。"
    said = (done.stderr or done.stdout).decode("utf-8", errors="replace").strip()
    return done.returncode, said


def valid_branch(name: str) -> bool:
    """`feature/` and then letters, digits and `_`: no `-`, `.` or `/` in the name."""
    return bool(BRANCH.match(name))


def tracked_files(repo: Repo, commit: str, relative: str, timeout: int = DEFAULT_GIT_TIMEOUT) -> List[Tuple[str, str, str]]:
    """(mode, blob sha, path) of every file `commit` has at `relative`: that file, or everything under that folder."""
    raw = git(repo, "ls-tree", "-r", "-z", commit, "--", relative, timeout=timeout).decode("utf-8", errors="replace")
    found = []
    for line in raw.split("\0"):
        if not line:
            continue
        info, _, path = line.partition("\t")
        mode, _kind, blob = info.split(" ")
        found.append((mode, blob, path))
    return found


def read_blob(repo: Repo, blob: str, timeout: int = DEFAULT_GIT_TIMEOUT) -> bytes:
    """The bytes of a file as git stores it: no line-ending conversion."""
    return git(repo, "cat-file", "blob", blob, timeout=timeout)


def text(repo: Repo, *arguments: str, timeout: int = DEFAULT_GIT_TIMEOUT) -> str:
    return git(repo, *arguments, timeout=timeout).decode("utf-8", errors="replace").strip()


def ref_commit(repo: Repo, timeout: int = DEFAULT_GIT_TIMEOUT) -> str:
    """The commit `base_ref` points to now, or an empty string when the repository has no such branch."""
    out = git(repo, "rev-parse", "--verify", "--quiet", f"{repo.base_ref}^{{commit}}", timeout=timeout, allow_failure=True)
    return out.decode("ascii", errors="replace").strip()


def commit_date(repo: Repo, commit: str, timeout: int = DEFAULT_GIT_TIMEOUT) -> str:
    return text(repo, "log", "-1", "--format=%cI", commit, timeout=timeout)


def current_branch(repo: Repo, timeout: int = DEFAULT_GIT_TIMEOUT) -> str:
    """The checked-out branch, or `(detached)`."""
    out = git(repo, "symbolic-ref", "--short", "-q", "HEAD", timeout=timeout, allow_failure=True)
    return out.decode("utf-8", errors="replace").strip() or "(detached)"


def dirty_paths(repo: Repo, timeout: int = DEFAULT_GIT_TIMEOUT) -> List[str]:
    """Paths with uncommitted changes, untracked files included. Empty means a clean working tree."""
    raw = git(repo, "status", "--porcelain", "-z", "--untracked-files=all", timeout=timeout)
    found = []
    for entry in raw.decode("utf-8", errors="replace").split("\0"):
        if len(entry) > 3:
            found.append(entry[3:])
    return found


def summary(repo: Repo, timeout: int = DEFAULT_GIT_TIMEOUT) -> Dict[str, Any]:
    """What a person needs to see about one repository."""
    commit = ref_commit(repo, timeout)
    dirty = dirty_paths(repo, timeout)
    return {
        "name": repo.name,
        "path": str(repo.path),
        "base_ref": repo.base_ref,
        "base_commit": commit[:12],
        "base_commit_date": commit_date(repo, commit, timeout) if commit else "",
        "has_base_ref": bool(commit),
        "current_branch": current_branch(repo, timeout),
        "clean": not dirty,
        "uncommitted_files": len(dirty),
        "refused_paths": repo.refused_paths,
    }


# --- where the harness itself lives -----------------------------------------------------------


def location_warnings(root: str, windows: Optional[bool] = None) -> List[str]:
    """Paths that cause trouble for request folders: a long one (Windows stops at 260) and a synced one (OneDrive)."""
    found = []
    on_windows = os.name == "nt" if windows is None else windows
    if on_windows and len(root) > LONG_PATH_WARNING:
        found.append(
            f"harness 的路径有 {len(root)} 个字符。请求目录和仓库内的路径还要再加上一百多个字符，Windows 默认上限是 260。"
            "把 harness 放到短路径，例如 C:\\dev\\harness"
        )
    if "onedrive" in root.lower():
        found.append("harness 在 OneDrive 下。请求目录里的文件会被同步，数量多时很慢，也可能同步到一半出错。放到不同步的位置，例如 C:\\dev\\harness")
    return found
