"""Repository paths. HARNESS_ROOT overrides the root (used by tests)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Where L3 requests live. Core knows it so modules that only read a request (eval) need not import the request module.
REQUESTS_DIR = ".workspace/sandbox/requests"


CLI_PATH = ".harness/engine/cli.py"


def is_windows(windows: Optional[bool] = None) -> bool:
    return os.name == "nt" if windows is None else windows


def python_command(windows: Optional[bool] = None) -> str:
    """The interpreter name to type. Windows has `python` and often no `python3`; macOS and Linux have `python3`."""
    return "python" if is_windows(windows) else "python3"


SHORT_COMMAND = "harness"


def cli_command(windows: Optional[bool] = None) -> str:
    """The prefix of every harness command shown to an agent or a person: the short command (`.harness/bin/`, in PATH).

    Putting it into PATH is a required setup step; `doctor` checks it. `windows` is kept for callers that pass it.
    """
    return SHORT_COMMAND


def mkdir_command(windows: Optional[bool] = None) -> str:
    """Make a folder and its parents: `mkdir` does it on Windows (PowerShell and cmd), `mkdir -p` elsewhere."""
    return "mkdir" if is_windows(windows) else "mkdir -p"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_root() -> Path:
    override = os.environ.get("HARNESS_ROOT")
    if override:
        return Path(override).resolve()
    # .harness/engine/core/paths.py -> repository root
    return Path(__file__).resolve().parents[3]


def harness_dir(root: Path) -> Path:
    return root / ".harness"


def policies_dir(root: Path) -> Path:
    return root / ".harness" / "policies"


def registry_path(root: Path) -> Path:
    return root / ".harness" / "registry.json"


def runtime_dir(root: Path) -> Path:
    return root / ".harness" / "runtime"


def state_dir(root: Path, surface: str) -> Path:
    return runtime_dir(root) / "state" / surface


def logs_dir(root: Path) -> Path:
    return runtime_dir(root) / "logs"
