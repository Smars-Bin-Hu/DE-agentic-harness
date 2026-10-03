"""request.json: read, validate, write under a lock. Only this module writes it."""

from __future__ import annotations

import hashlib
import json
import random
import re
import string
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator

from core import config, schema
from core.paths import utc_now
from core.state import atomic_write, state_lock

from . import layout
from .layout import CommandError

SCHEMA_VERSION = 1


def contract(root: Path, name: str) -> Dict[str, Any]:
    return config.read_json(root / ".harness" / "contracts" / f"{name}.schema.json")


def validate(root: Path, name: str, value: Any, what: str) -> None:
    schema.check(value, contract(root, name), what)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slug(title: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:30].strip("-")
    return text or "task"


def new_request_id(root: Path, title: str) -> str:
    """`<yyyymmdd-HHMM>-<slug>-<4 random>`: readable, and not likely to clash."""
    stamp = time.strftime("%Y%m%d-%H%M")
    for _ in range(50):
        suffix = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(4))
        candidate = f"{stamp}-{slug(title)}-{suffix}"
        if not layout.request_dir(root, candidate).exists():
            return candidate
    raise CommandError("建不出不重复的请求 id，稍后再试。")


def empty_request(request_id: str, title: str, session_id: str, surface: str, target_mode: bool = False, task: str = "", branch: str = "") -> Dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "title": title,
        "session_id": session_id,
        "surface": surface,
        "status": "open",
        "status_reason": "",
        "created_at": now,
        "updated_at": now,
        "attempt": 0,
        "attempts": [],
        "brief": {"version": 0, "sha256": "", "entries": 0},
        "pending_dispatch": [],
        "inputs": [],
        "promote": {"state": "none"},
        "target_mode": target_mode,
        "task": task,
        "branch": branch,
        "targets": {},
        "target_files": {},
    }


def write_request(root: Path, directory: Path, data: Dict[str, Any]) -> None:
    data["updated_at"] = utc_now()
    validate(root, "request", data, "request.json")
    atomic_write(layout.request_file(directory), data)


def read_json_file(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_request(root: Path, request_id: str) -> Dict[str, Any]:
    directory = layout.request_dir(root, request_id)
    path = layout.request_file(directory)
    if not path.exists():
        raise CommandError(f"没有请求 `{request_id}`。用 `request new` 建立，或检查 id 有没有抄对。")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    validate(root, "request", data, "request.json")
    return data


@contextmanager
def locked(root: Path, request_id: str) -> Iterator[Dict[str, Any]]:
    """Lock request.json, yield its data, write it back if the block ends without an exception."""
    directory = layout.request_dir(root, request_id)
    path = layout.request_file(directory)
    if not path.exists():
        raise CommandError(f"没有请求 `{request_id}`。用 `request new` 建立，或检查 id 有没有抄对。")
    with state_lock(path):
        data = read_request(root, request_id)
        yield data
        write_request(root, directory, data)


def require_open(data: Dict[str, Any]) -> None:
    if data["status"] != "open":
        raise CommandError(
            f"请求已经结束（{data['status']}），不能再改。需要继续时，用 `request new` 建一个新请求。"
        )
