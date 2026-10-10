"""How the CLI prints: the `cli` policy. Reading it never fails: a missing or broken policy means the default."""

from __future__ import annotations

import locale
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from . import config
from .paths import repo_root

POLICY_NAME = "cli"
AUTO = "auto"
CHOICES = (AUTO, "utf-8")
SAMPLE = "中文样例：成果已写入"


def setting(root: Optional[Path] = None) -> str:
    """`auto` or `utf-8`, as the policy says. Anything else, or a policy that cannot be read, is `auto`."""
    try:
        value = config.load_policy(root or repo_root(), POLICY_NAME)["output"]["encoding"]
    except Exception:  # noqa: BLE001 - printing must work with a broken policy; doctor reports it
        return AUTO
    return value if value in CHOICES else AUTO


def configured_encoding(root: Optional[Path] = None) -> str:
    """The encoding to force on stdout and stderr, or an empty string to leave them as they are."""
    value = setting(root)
    return "" if value == AUTO else value


def code_pages() -> Dict[str, int]:
    """Windows only: the console output code page and the ANSI code page. Empty elsewhere."""
    if sys.platform != "win32":
        return {}
    try:
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        return {"console_output": int(kernel.GetConsoleOutputCP()), "ansi": int(kernel.GetACP())}
    except Exception:  # noqa: BLE001
        return {}


def facts(stream: Any = None) -> Dict[str, Any]:
    stream = stream if stream is not None else sys.stdout
    try:
        terminal = bool(stream.isatty())
    except Exception:  # noqa: BLE001
        terminal = False
    return {
        "stdout_encoding": getattr(stream, "encoding", "") or "",
        "terminal": terminal,
        "preferred": locale.getpreferredencoding(False),
        "code_pages": code_pages(),
    }


def shows(text: str, encoding: str) -> bool:
    """True when `encoding` can write `text` as it is (no \\uXXXX)."""
    try:
        text.encode(encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        return False
    return True
