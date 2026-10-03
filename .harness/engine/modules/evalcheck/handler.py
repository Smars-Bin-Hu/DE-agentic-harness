"""evalcheck subscribes to no event: it only reads what other modules wrote. `doctor` checks the scenario files."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from core.context import Context
from core.events import Decision, HookEvent

from . import scenario

NAME = "evalcheck"


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    return None


def doctor(root: Path) -> List[str]:
    """Errors in the scenario files, for `cli doctor`."""
    return scenario.problems(root)
