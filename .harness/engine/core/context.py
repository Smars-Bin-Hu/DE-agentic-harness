"""What a module gets besides the event: the session state and policies."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from . import config
from .state import effective_level


class Context:
    def __init__(self, root: Path, state: Dict[str, Any]) -> None:
        self.root = root
        self.state = state
        self._policies: Dict[str, Any] = {}

    def module_state(self, name: str) -> Dict[str, Any]:
        return self.state["modules"].setdefault(name, {})

    def policy(self, name: str) -> Dict[str, Any]:
        if name not in self._policies:
            self._policies[name] = config.load_policy(self.root, name)
        return self._policies[name]

    @property
    def level(self) -> int:
        return effective_level(self.state)
