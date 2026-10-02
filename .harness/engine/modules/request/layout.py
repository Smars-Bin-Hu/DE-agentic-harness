"""Where things live inside a request folder (00 section 6.1). One place, so no other file builds these paths."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import Optional

REQUESTS_DIR = ".workspace/sandbox/requests"
ROLES = ("builder", "reviewer")
REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class CommandError(Exception):
    """A refused command. The message says why and what to do next."""


def attempt_name(number: int) -> str:
    return f"attempt-{number:03d}"


def requests_root(root: Path) -> Path:
    return root / REQUESTS_DIR


def request_dir(root: Path, request_id: str) -> Path:
    if not REQUEST_ID.match(request_id) or ".." in request_id:
        raise CommandError(f"请求 id `{request_id}` 不合法。用 `request new` 返回的 request_id。")
    return requests_root(root) / request_id


def request_file(directory: Path) -> Path:
    return directory / "request.json"


def init_inputs(directory: Path) -> Path:
    return directory / "handoffs" / "orchestrator" / "init-inputs"


def brief_file(directory: Path) -> Path:
    return init_inputs(directory) / "knowledge-brief.md"


def brief_snapshot(directory: Path, version: int) -> Path:
    return init_inputs(directory) / "brief-history" / f"v{version:03d}.md"


def package_dir(directory: Path, number: int, role: str) -> Path:
    return directory / "handoffs" / "orchestrator" / attempt_name(number) / f"to-{role}"


def outputs_dir(directory: Path, number: int, role: str) -> Path:
    return directory / role / "outputs" / attempt_name(number)


def handoff_file(directory: Path, number: int, role: str) -> Path:
    return directory / "handoffs" / role / attempt_name(number) / "handoff.json"


def relative_name(raw: str, what: str = "路径") -> str:
    """A clean relative path inside a folder: no drive, no `..`, no leading slash. Returns it with `/`."""
    text = raw.strip().replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise CommandError(f"{what} `{raw}` 必须是相对路径。")
    clean = posixpath.normpath(text)
    if clean == "." or clean == ".." or clean.startswith("../"):
        raise CommandError(f"{what} `{raw}` 不能指向目录之外。")
    return clean


def inside(root: Path, path: Path) -> Optional[str]:
    """`path` relative to `root` with `/`, after resolving links, or None when it is outside."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return relative.as_posix()
