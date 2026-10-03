"""Path handling for the gate: one spelling for relative, absolute, `..`, Windows `\\` and any letter case.

Everything is compared as a lowercase, forward-slash path relative to the repository root.
"""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path
from typing import List, Optional, Pattern
from urllib.parse import unquote

_DRIVE = re.compile(r"^[A-Za-z]:/")


def _normal(raw: str) -> str:
    text = raw.strip().strip("\"'")
    if text.lower().startswith("file://"):
        text = unquote(text[7:])
        if re.match(r"^/[A-Za-z]:/", text.replace("\\", "/")):
            text = text[1:]  # file:///C:/x
    text = re.sub(r"/{2,}", "/", text.replace("\\", "/"))
    drive = ""
    if _DRIVE.match(text):
        drive, text = text[:2], text[2:]
    return drive + posixpath.normpath(text or ".")


normal = _normal  # for callers outside this module


def _is_absolute(path: str) -> bool:
    return path.startswith("/") or bool(_DRIVE.match(path))


def _inside(path: str, root: str) -> Optional[str]:
    """`path` relative to `root` (both normal, lowercase compare), or None when it is outside."""
    if path.lower() == root.lower():
        return "."
    prefix = root.rstrip("/") + "/"
    if path.lower().startswith(prefix.lower()):
        return path[len(prefix):]
    return None


def resolve(raw: str, root: Path, cwd: str = "") -> List[str]:
    """Where a tool path points, as absolute paths (normal form). One entry per way to read it.

    A relative path may be meant against the repo root or the payload's `cwd`, and a symlink may hide the real path.
    """
    if not raw or not raw.strip():
        return []
    roots = {_normal(str(root))}
    try:
        roots.add(_normal(os.path.realpath(str(root))))
    except OSError:
        pass
    path = _normal(raw)
    bases = [path] if _is_absolute(path) else []
    if not bases:
        bases.append(posixpath.normpath(_normal(str(root)) + "/" + path))
        here = _normal(cwd) if cwd else ""
        if here and _is_absolute(here) and any(_inside(here, name) is not None for name in roots):
            bases.append(posixpath.normpath(here + "/" + path))  # a cwd outside the repo says nothing about this path
    for base in list(bases):
        try:
            real = _normal(os.path.realpath(base))
        except OSError:
            real = base
        if real != base:
            bases.append(real)
    return bases


def repo_relative(raw: str, root: Path, cwd: str = "") -> List[Optional[str]]:
    """Where a tool path points, as repo-relative paths. One entry per way to read it; None means outside the repo.

    The gate treats a path as guarded when any reading hits a guardrail, and as inside a folder only when all do.
    """
    roots = {_normal(str(root))}
    try:
        roots.add(_normal(os.path.realpath(str(root))))
    except OSError:
        pass
    found: List[Optional[str]] = []
    for base in resolve(raw, root, cwd):
        relative = next((hit for hit in (_inside(base, root_text) for root_text in sorted(roots)) if hit is not None), None)
        if relative not in found:
            found.append(relative)
    return found


def inside(path: str, folder: Path) -> List[str]:
    """`path` (normal, absolute) relative to `folder`, once for the folder as written and once for its real path."""
    names = {_normal(str(folder))}
    try:
        names.add(_normal(os.path.realpath(str(folder))))
    except OSError:
        pass
    return [hit for hit in (_inside(path, name) for name in sorted(names)) if hit is not None]


# Windows reads these as the same folder as `.git`: `.git.`, `.git ` (trailing dots and spaces are dropped), the short name
# `GIT~1`, and an NTFS stream suffix (`.git::$INDEX_ALLOCATION`).
_GIT_NAMES = re.compile(r"^(?:\.git|git~\d+)$", re.IGNORECASE)


def windows_name(segment: str) -> str:
    """One path segment the way Windows spells it: no stream suffix, no trailing dots or spaces."""
    text = segment.split(":", 1)[0] if ":" in segment and not _DRIVE.match(segment + "/") else segment
    return text if text in ("", ".", "..") else text.rstrip(". ")


def has_git_folder(path: str) -> bool:
    """Whether a path has a `.git` segment, in any spelling Windows treats as the same."""
    return any(_GIT_NAMES.match(windows_name(part)) for part in path.replace("\\", "/").split("/"))


def glob_regex(pattern: str) -> Pattern[str]:
    """`**` crosses folders, `*` and `?` stay inside one. A trailing `/**` also matches the folder itself."""
    text = pattern.strip().replace("\\", "/")
    if text.startswith("./"):
        text = text[2:]
    tail = ""
    if text.endswith("/**"):
        text, tail = text[:-3], "(?:/.*)?"
    body = ""
    index = 0
    while index < len(text):
        if text.startswith("**", index):
            body, index = body + ".*", index + 2
        elif text[index] == "*":
            body, index = body + "[^/]*", index + 1
        elif text[index] == "?":
            body, index = body + "[^/]", index + 1
        else:
            body, index = body + re.escape(text[index]), index + 1
    return re.compile("^" + body + tail + "$", re.IGNORECASE)


def command_regex(patterns: List[str]) -> Pattern[str]:
    """Find any of the guardrail paths inside a terminal command (already normalized to `/`)."""
    parts = []
    for pattern in patterns:
        text = pattern.strip().replace("\\", "/")
        if text.startswith("./"):
            text = text[2:]
        if text.endswith("/**"):
            text = text[:-3]
        body = ""
        index = 0
        while index < len(text):
            if text.startswith("**", index):
                body, index = body + "[^\\s\"']*", index + 2
            elif text[index] == "*":
                body, index = body + "[^\\s\"'/]*", index + 1
            elif text[index] == "?":
                body, index = body + "[^\\s\"'/]", index + 1
            else:
                body, index = body + re.escape(text[index]), index + 1
        parts.append(body)
    return re.compile(r"(?<![\w.-])(?:" + "|".join(parts) + r")(?![\w.-])", re.IGNORECASE)
