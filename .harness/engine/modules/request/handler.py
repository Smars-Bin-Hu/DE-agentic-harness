"""The request module has no hook behavior yet: the CLI does the work.

The hook side comes later: "a subagent call needs a dispatch" (M4-4) and the SubagentStart injection (M4-7).
"""

from __future__ import annotations

from typing import Optional

from core.context import Context
from core.events import Decision, HookEvent

NAME = "request"


def handle(event: HookEvent, ctx: Context) -> Optional[Decision]:
    return None
