"""JSONL logs under .harness/runtime/logs/. Logging must never raise."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any, Dict

from .paths import logs_dir, utc_now


def _append(root: Path, filename: str, record: Dict[str, Any]) -> None:
    try:
        directory = logs_dir(root)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / filename).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log_error(root: Path, where: str, error: BaseException) -> None:
    _append(
        root,
        "hook-errors.jsonl",
        {
            "at": utc_now(),
            "where": where,
            "error": f"{type(error).__name__}: {error}",
            "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))[-2000:],
        },
    )


def log_call(root: Path, record: Dict[str, Any]) -> None:
    """One line per hook.py call. Used to check that every event runs once, and how long it takes."""
    record = dict(record)
    record["at"] = utc_now()
    _append(root, "hook-calls.jsonl", record)
