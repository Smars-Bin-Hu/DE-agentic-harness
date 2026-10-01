"""Read the user's prompt: level switch markers and skip markers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .policy import SWITCHABLE_LEVELS, skip_markers

# A pasted prompt can start with whitespace or a markdown code fence line (seen in the B1 recording).
_LEADING = r"\s*(?:```[^\n]*\n\s*)?"


def _marker_pattern(marker: str) -> str:
    text = re.escape(marker)
    # "/l2" must not match "/l2x". "[L2]" ends with a bracket and needs no boundary.
    return text + (r"(?!\w)" if marker[-1].isalnum() else "")


def switch_pattern(policy: Dict[str, Any]) -> "re.Pattern[str]":
    names: List[Tuple[str, int]] = []
    for level in SWITCHABLE_LEVELS:
        for marker in policy["switch_markers"][str(level)]:
            names.append((marker, level))
    # Longer markers first, so one marker that starts with another cannot hide it.
    names.sort(key=lambda item: -len(item[0]))
    return re.compile(_LEADING + "(" + "|".join(_marker_pattern(m) for m, _ in names) + ")", re.IGNORECASE)


def parse_switch(prompt: str, policy: Dict[str, Any]) -> Optional[Tuple[int, str]]:
    """The level asked for by a marker at the start of the prompt, with the marker as written. None if no marker."""
    found = switch_pattern(policy).match(prompt)
    if not found:
        return None
    written = found.group(1)
    for level in SWITCHABLE_LEVELS:
        if written.lower() in [m.lower() for m in policy["switch_markers"][str(level)]]:
            return level, written
    return None


def wants_skip_verify(prompt: str, policy: Dict[str, Any]) -> bool:
    """A skip marker anywhere in the user's prompt. It only covers that one prompt."""
    lowered = prompt.lower()
    return any(marker.lower() in lowered for marker in skip_markers(policy))
