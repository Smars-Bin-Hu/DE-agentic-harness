"""Who uses this copy of the harness: the `user` policy. An agent asks for the name with `harness user`."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict

from . import config

POLICY_NAME = "user"
GIT_TIMEOUT = 5


def git_name(root: Path) -> str:
    try:
        done = subprocess.run(
            ["git", "config", "user.name"], cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=GIT_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def who(root: Path) -> Dict[str, str]:
    """The name and where it comes from: `user.override.json`, `git` or `none`."""
    try:
        name = config.load_policy(root, POLICY_NAME).get("name", "")
    except Exception:  # noqa: BLE001 - a broken policy is doctor's to report
        name = ""
    if isinstance(name, str) and name.strip():
        return {"name": name.strip(), "source": f"{POLICY_NAME}{config.OVERRIDE_SUFFIX}"}
    name = git_name(root)
    return {"name": name, "source": "git" if name else "none"}
