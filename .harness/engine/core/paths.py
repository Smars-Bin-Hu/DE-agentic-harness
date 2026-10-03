"""Repository paths. HARNESS_ROOT overrides the root (used by tests)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path


# Where L3 requests live. Core knows it so modules that only read a request (eval) need not import the request module.
REQUESTS_DIR = ".workspace/sandbox/requests"


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
