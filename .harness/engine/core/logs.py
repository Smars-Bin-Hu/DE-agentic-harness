"""JSONL logs under .harness/runtime/logs/. Logging must never raise.

  hook-errors.jsonl                 what went wrong inside the hook (one file)
  <surface>/<session id>.jsonl      one line per hook call of that session (written by the observe module)
"""

from __future__ import annotations

import json
import re
import traceback
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

from .paths import logs_dir, utc_now

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _append(root: Path, relative: str, record: Dict[str, Any]) -> None:
    try:
        path = logs_dir(root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    except Exception:
        pass


def safe_name(value: str) -> str:
    """A session id as a file name. Ids are uuids; anything else is made safe, not rejected."""
    return _UNSAFE.sub("_", value).replace("..", "_").lstrip(".")[:120] or "unknown"


def session_log_path(root: Path, surface: str, session_id: str) -> Path:
    return logs_dir(root) / safe_name(surface) / (safe_name(session_id) + ".jsonl")


def log_error(root: Path, where: str, error: BaseException, sample: str = "") -> None:
    """`sample` is the start of the raw hook input. It shows the shape of a payload the engine could not read."""
    entry = {
        "at": utc_now(),
        "where": where,
        "error": f"{type(error).__name__}: {error}",
        "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))[-2000:],
    }
    if sample:
        entry["sample"] = sample[:1500]
    _append(root, "hook-errors.jsonl", entry)


def log_call(root: Path, record: Dict[str, Any]) -> None:
    """One line per hook.py call, in the log of its session. A call with no session (the input was unreadable) is in hook-errors."""
    if not record.get("session_id"):
        return
    record = dict(record)
    record["at"] = utc_now()
    _append(root, f"{safe_name(str(record.get('surface') or 'unknown'))}/{safe_name(str(record['session_id']))}.jsonl", record)


def read_lines(path: Path) -> List[Dict[str, Any]]:
    """The lines of a JSONL file that parse. A half-written last line is skipped."""
    rows: List[Dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def read_session(root: Path, surface: str, session_id: str) -> List[Dict[str, Any]]:
    return read_lines(session_log_path(root, surface, session_id))


def session_files(root: Path) -> Iterator[Tuple[str, Path]]:
    """(surface, file) for every session log, oldest first by modification time."""
    base = logs_dir(root)
    if not base.is_dir():
        return iter(())
    found = [(path.parent.name, path) for path in base.glob("*/*.jsonl")]
    found.sort(key=lambda item: (item[1].stat().st_mtime, item[1].name))
    return iter(found)
