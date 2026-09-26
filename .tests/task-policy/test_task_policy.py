from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE = REPOSITORY_ROOT / ".harness" / "task-policy" / "task_policy.py"
POLICY = REPOSITORY_ROOT / ".harness" / "policies" / "task-levels.json"


class TaskPolicyEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        policy_directory = self.root / ".harness" / "policies"
        policy_directory.mkdir(parents=True)
        shutil.copy(POLICY, policy_directory / "task-levels.json")
        self.environment = {**os.environ, "TASK_POLICY_ROOT": str(self.root)}

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def execute(self, *arguments: str, payload: dict | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ENGINE), *arguments],
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            env=self.environment,
            check=False,
        )

    def output(self, completed: subprocess.CompletedProcess[str]) -> dict:
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    @staticmethod
    def hook_payload(session_id: str, tool_name: str = "Read", tool_input: dict | None = None) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": "/workspace",
            "tool_name": tool_name,
            "tool_input": tool_input or {},
        }

    def user_prompt(self, runtime: str, session_id: str) -> dict:
        return self.output(
            self.execute(
                "hook",
                "--runtime",
                runtime,
                "--event",
                "UserPromptSubmit",
                payload={"session_id": session_id, "prompt": "start work"},
            )
        )

    def status(self, runtime: str, session_id: str) -> dict:
        return self.output(self.execute("status", "--runtime", runtime, "--session-id", session_id))

    def set_level(self, runtime: str, session_id: str, level: int, reason: str = "test transition") -> dict:
        return self.output(
            self.execute(
                "set-level",
                "--runtime",
                runtime,
                "--session-id",
                session_id,
                "--level",
                str(level),
                "--reason",
                reason,
            )
        )

    def pre_tool(self, runtime: str, session_id: str, tool_name: str, tool_input: dict | None = None) -> dict:
        return self.output(
            self.execute(
                "hook",
                "--runtime",
                runtime,
                "--event",
                "PreToolUse",
                payload=self.hook_payload(session_id, tool_name, tool_input),
            )
        )

    def post_tool(self, runtime: str, session_id: str, tool_name: str = "Read") -> dict:
        return self.output(
            self.execute(
                "hook",
                "--runtime",
                runtime,
                "--event",
                "PostToolUse",
                payload=self.hook_payload(session_id, tool_name),
            )
        )

    def test_policy_has_three_valid_levels(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(policy["schema_version"], 1)
        self.assertEqual(
            [policy["levels"][str(level)]["execution_budget"]["repository_searches"] for level in (1, 2, 3)],
            [2, 8, 25],
        )
        self.assertEqual(
            [policy["levels"][str(level)]["execution_budget"]["observed_tool_calls"] for level in (1, 2, 3)],
            [15, 40, 120],
        )
        self.assertEqual(
            [policy["levels"][str(level)]["execution_budget"]["subagents_created"] for level in (1, 2, 3)],
            [0, 0, 4],
        )

    def test_lifecycle_preserves_follow_up_and_resets_next_task(self) -> None:
        self.user_prompt("copilot", "lifecycle")
        before = self.status("copilot", "lifecycle")
        first_task_id = before["task"]["id"]
        self.set_level("copilot", "lifecycle", 2, "Multiple related files need a short plan.")
        self.pre_tool("copilot", "lifecycle", "Read")

        self.user_prompt("copilot", "lifecycle")
        follow_up = self.status("copilot", "lifecycle")
        self.assertEqual(follow_up["task"]["id"], first_task_id)
        self.assertEqual(follow_up["task"]["level"], 2)
        self.assertEqual(follow_up["counters"]["observed_tool_calls"], 1)

        completed = self.output(
            self.execute(
                "complete",
                "--runtime",
                "copilot",
                "--session-id",
                "lifecycle",
                "--reason",
                "Validated the requested change.",
            )
        )
        self.assertEqual(completed["task"]["status"], "completed")
        self.assertEqual(completed["task"]["level"], 1)

        self.user_prompt("copilot", "lifecycle")
        next_task = self.status("copilot", "lifecycle")
        self.assertEqual(next_task["task"]["status"], "active")
        self.assertEqual(next_task["task"]["level"], 1)
        self.assertNotEqual(next_task["task"]["id"], first_task_id)
        self.assertEqual(next_task["counters"]["observed_tool_calls"], 0)
        self.assertEqual(next_task["task_history"][-1]["id"], first_task_id)
        self.assertEqual(next_task["task_history"][-1]["status"], "completed")

    def test_transition_preserves_counters_and_invalid_level_fails(self) -> None:
        self.user_prompt("copilot", "transition")
        self.pre_tool("copilot", "transition", "Read")
        upgraded = self.set_level("copilot", "transition", 3, "Cross-system RCA requires delegation.")
        self.assertEqual(upgraded["counters"]["observed_tool_calls"], 1)
        self.assertEqual(upgraded["task"]["transitions"][-1]["type"], "upgrade")

        downgraded = self.set_level("copilot", "transition", 1, "Only a deterministic config edit remains.")
        self.assertEqual(downgraded["counters"]["observed_tool_calls"], 1)
        self.assertEqual(downgraded["task"]["transitions"][-1]["type"], "downgrade")

        invalid = self.execute(
            "set-level",
            "--runtime",
            "copilot",
            "--session-id",
            "transition",
            "--level",
            "9",
            "--reason",
            "invalid",
        )
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("Unknown Task Level", invalid.stderr)

    def test_replace_active_task_archives_the_previous_task(self) -> None:
        self.user_prompt("copilot", "replace")
        original_id = self.status("copilot", "replace")["task"]["id"]
        replacement = self.output(
            self.execute(
                "begin",
                "--runtime",
                "copilot",
                "--session-id",
                "replace",
                "--replace",
                "--reason",
                "The user changed the requested outcome.",
            )
        )
        self.assertNotEqual(replacement["task"]["id"], original_id)
        self.assertEqual(replacement["task"]["level"], 1)
        self.assertEqual(replacement["task_history"][-1]["id"], original_id)
        self.assertEqual(replacement["task_history"][-1]["completion_reason"], "replaced")

    def test_copilot_uses_copilot_decision_schema(self) -> None:
        self.user_prompt("copilot", "copilot-delegation")
        denied = self.pre_tool("copilot", "copilot-delegation", "Agent")
        self.assertEqual(denied["permissionDecision"], "deny")
        self.assertIn("Task Level 1", denied["permissionDecisionReason"])

    def test_l3_limits_subagents_to_four(self) -> None:
        self.user_prompt("copilot", "delegation")
        self.set_level("copilot", "delegation", 3)
        for _ in range(4):
            self.assertEqual(self.pre_tool("copilot", "delegation", "Agent"), {})
        fifth = self.pre_tool("copilot", "delegation", "Agent")
        self.assertEqual(fifth["permissionDecision"], "deny")
        self.assertEqual(self.status("copilot", "delegation")["counters"]["subagents_created"], 4)

    def test_copilot_uses_copilot_warning_schema(self) -> None:
        self.user_prompt("copilot", "copilot-warning")
        self.pre_tool("copilot", "copilot-warning", "Grep")
        self.post_tool("copilot", "copilot-warning", "Grep")
        self.pre_tool("copilot", "copilot-warning", "Grep")
        warning = self.post_tool("copilot", "copilot-warning", "Grep")
        self.assertIn("repository_searches budget: 2/2", warning["additionalContext"])

    def test_soft_search_warning_is_emitted_once(self) -> None:
        self.user_prompt("copilot", "warning")
        self.pre_tool("copilot", "warning", "Grep")
        self.assertEqual(self.post_tool("copilot", "warning", "Grep"), {})

        self.pre_tool("copilot", "warning", "Grep")
        warning = self.post_tool("copilot", "warning", "Grep")
        self.assertIn("repository_searches budget: 2/2", warning["additionalContext"])
        self.assertEqual(self.post_tool("copilot", "warning", "Grep"), {})

    def test_session_state_is_isolated_by_session(self) -> None:
        self.user_prompt("copilot", "session-a")
        self.user_prompt("copilot", "session-b")
        self.set_level("copilot", "session-a", 3)
        self.assertEqual(self.status("copilot", "session-a")["task"]["level"], 3)
        self.assertEqual(self.status("copilot", "session-b")["task"]["level"], 1)
        self.assertTrue((self.root / ".harness" / "runtime" / "task-policy" / "copilot" / "session-a.json").exists())
        self.assertTrue((self.root / ".harness" / "runtime" / "task-policy" / "copilot" / "session-b.json").exists())

    def test_concurrent_updates_do_not_lose_tool_counts(self) -> None:
        self.user_prompt("copilot", "concurrent")

        def call_pre_tool(_: int) -> dict:
            return self.pre_tool("copilot", "concurrent", "Read")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(call_pre_tool, range(10)))
        self.assertEqual(results, [{}] * 10)
        self.assertEqual(self.status("copilot", "concurrent")["counters"]["observed_tool_calls"], 10)

    def test_hook_engine_fails_open_when_policy_is_missing(self) -> None:
        missing_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, missing_root)
        environment = {**os.environ, "TASK_POLICY_ROOT": str(missing_root)}
        completed = subprocess.run(
            [sys.executable, str(ENGINE), "hook", "--runtime", "copilot", "--event", "PreToolUse"],
            input=json.dumps(self.hook_payload("missing-policy", "Read")),
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout), {})
        self.assertTrue((missing_root / ".harness" / "runtime" / "task-policy" / "hook-errors.jsonl").exists())

    def test_hook_engine_fails_open_for_corrupted_state(self) -> None:
        self.user_prompt("copilot", "corrupt")
        state_file = self.root / ".harness" / "runtime" / "task-policy" / "copilot" / "corrupt.json"
        state_file.write_text("this is not json", encoding="utf-8")
        result = self.execute(
            "hook",
            "--runtime",
            "copilot",
            "--event",
            "PreToolUse",
            payload=self.hook_payload("corrupt", "Read"),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertTrue((self.root / ".harness" / "runtime" / "task-policy" / "hook-errors.jsonl").exists())


class TaskPolicyAdapterTests(unittest.TestCase):
    def test_hook_configurations_are_valid_json_and_reference_shared_engine(self) -> None:
        copilot = json.loads(
            (REPOSITORY_ROOT / ".github" / "hooks" / "task-level-policy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(copilot["hooks"]), {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"})
        copilot_command = copilot["hooks"]["PreToolUse"][0]["bash"]
        self.assertIn(".harness/task-policy/task_policy.py", copilot_command)


if __name__ == "__main__":
    unittest.main()
