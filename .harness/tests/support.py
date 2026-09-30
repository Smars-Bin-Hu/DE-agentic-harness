"""Shared test helpers. Tests run hook.py and cli.py as real subprocesses, with HARNESS_ROOT pointing at a temp root."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / ".harness" / "engine"
HOOK = ENGINE / "hook.py"
CLI = ENGINE / "cli.py"
POLICY = REPO / ".harness" / "policies" / "task-levels.json"
FIXTURES = REPO / ".harness" / "eval" / "fixtures" / "hooks" / "vscode"

if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))


def iter_session(name: str) -> Iterator[Dict[str, Any]]:
    with (FIXTURES / "sessions" / name).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_payload(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / "payloads" / name).read_text(encoding="utf-8"))


def payload(event: str, session_id: str, **fields: Any) -> Dict[str, Any]:
    """A VS Code payload in the recorded shape."""
    base = {
        "timestamp": "2026-01-01T00:00:00.000Z",
        "hook_event_name": event,
        "session_id": session_id,
        "transcript_path": "<VSCODE_STORAGE>/transcripts/x.jsonl",
        "cwd": "/workspace",
    }
    base.update(fields)
    return base


def pre_tool(session_id: str, tool_name: str, tool_input: Optional[dict] = None) -> Dict[str, Any]:
    return payload("PreToolUse", session_id, tool_name=tool_name, tool_input=tool_input or {}, tool_use_id="t1")


def post_tool(session_id: str, tool_name: str, tool_input: Optional[dict] = None, response: str = "") -> Dict[str, Any]:
    return payload(
        "PostToolUse", session_id, tool_name=tool_name, tool_input=tool_input or {}, tool_response=response, tool_use_id="t1"
    )


def make_root(root: Path, with_registry: bool = True, with_policy: bool = True) -> None:
    """Minimal harness root: registry and policies. The engine code always comes from the real repo."""
    (root / ".harness").mkdir(parents=True, exist_ok=True)
    if with_registry:
        shutil.copy(REPO / ".harness" / "registry.json", root / ".harness" / "registry.json")
    if with_policy:
        shutil.copytree(REPO / ".harness" / "policies", root / ".harness" / "policies")


class HarnessTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        make_root(self.root)
        self.env = {**os.environ, "HARNESS_ROOT": str(self.root)}

    # --- running the engine -------------------------------------------------------------------

    def run_script(self, script: Path, *arguments: str, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            input=stdin,
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=self.env,
            check=False,
        )

    def hook(self, data: Dict[str, Any]) -> Dict[str, Any]:
        completed = self.run_script(HOOK, stdin=json.dumps(data))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def cli(self, *arguments: str) -> subprocess.CompletedProcess:
        return self.run_script(CLI, *arguments)

    def cli_json(self, *arguments: str) -> Dict[str, Any]:
        completed = self.cli(*arguments)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    # --- state --------------------------------------------------------------------------------

    def session_state(self, session_id: str) -> Dict[str, Any]:
        return self.cli_json("level", "status", "--session-id", session_id)

    def task_level_state(self, session_id: str) -> Dict[str, Any]:
        return self.session_state(session_id)["modules"]["task_level"]

    def state_file(self, session_id: str) -> Path:
        return self.root / ".harness" / "runtime" / "state" / "vscode" / f"{session_id}.json"

    def log_lines(self, filename: str) -> List[Dict[str, Any]]:
        path = self.root / ".harness" / "runtime" / "logs" / filename
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def set_level(self, session_id: str, level: int, reason: str = "test transition") -> Dict[str, Any]:
        return self.cli_json("level", "set", "--session-id", session_id, "--level", str(level), "--reason", reason)
