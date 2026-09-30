"""Fail-open: a broken module or hook must never block normal work (AGENTS.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .logs import log_error


def call_safely(root: Path, where: str, function: Callable[..., Any], *args: Any, default: Any = None) -> Any:
    """Run function. On any exception, log it and return default."""
    try:
        return function(*args)
    except Exception as error:
        log_error(root, where, error)
        return default
