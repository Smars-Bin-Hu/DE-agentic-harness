"""Task Level behavior. Migrated from the first engine tests.

The scenarios are the same as before the engine split. What changed: real VS Code tool names
(runSubagent, grep_search, read_file), the hookSpecificOutput format, and the new state layout.
"""

from __future__ import annotations

import concurrent.futures
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from support import (
    HOOK,
    POLICY,
    HarnessTestCase,
    make_root,
    payload,
    post_tool,
    pre_tool,
)

SUBAGENT_INPUT = {"agentName": "verifier", "prompt": "check it", "description": "check"}
GREP_INPUT = {"query": "sandbox", "isRegexp": False}


class TaskLevelTests(HarnessTestCase):
    def user_prompt(self, session_id: str, text: str = "start work") -> dict:
        return self.hook(payload("UserPromptSubmit", session_id, prompt=text))

    def pre(self, session_id: str, tool: str = "read_file", tool_input: dict | None = None) -> dict:
        return self.hook(pre_tool(session_id, tool, tool_input))

    def post(self, session_id: str, tool: str = "read_file", tool_input: dict | None = None) -> dict:
        return self.hook(post_tool(session_id, tool, tool_input))

    def test_policy_has_three_valid_levels(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(policy["schema_version"], 1)
        budgets = [policy["levels"][str(level)]["execution_budget"] for level in (1, 2, 3)]
        self.assertEqual([b["repository_searches"] for b in budgets], [2, 8, 25])
        self.assertEqual([b["observed_tool_calls"] for b in budgets], [15, 40, 120])
        self.assertEqual([b["subagents_created"] for b in budgets], [0, 0, 4])

    def test_lifecycle_preserves_follow_up_and_resets_next_task(self) -> None:
        self.user_prompt("lifecycle")
        first_task_id = self.task_level_state("lifecycle")["task"]["id"]
        self.set_level("lifecycle", 2, "Multiple related files need a short plan.")
        self.pre("lifecycle")

        self.user_prompt("lifecycle")
        follow_up = self.task_level_state("lifecycle")
        self.assertEqual(follow_up["task"]["id"], first_task_id)
        self.assertEqual(follow_up["task"]["level"], 2)
        self.assertEqual(follow_up["counters"]["observed_tool_calls"], 1)

        completed = self.cli_json(
            "level", "complete", "--session-id", "lifecycle", "--reason", "Validated the requested change."
        )["modules"]["task_level"]
        self.assertEqual(completed["task"]["status"], "completed")
        self.assertEqual(completed["task"]["level"], 1)

        self.user_prompt("lifecycle")
        next_task = self.task_level_state("lifecycle")
        self.assertEqual(next_task["task"]["status"], "active")
        self.assertEqual(next_task["task"]["level"], 1)
        self.assertNotEqual(next_task["task"]["id"], first_task_id)
        self.assertEqual(next_task["counters"]["observed_tool_calls"], 0)
        self.assertEqual(next_task["task_history"][-1]["id"], first_task_id)
        self.assertEqual(next_task["task_history"][-1]["status"], "completed")

    def test_transition_preserves_counters_and_invalid_level_fails(self) -> None:
        self.user_prompt("transition")
        self.pre("transition")
        upgraded = self.set_level("transition", 3, "Cross-system RCA requires delegation.")["modules"]["task_level"]
        self.assertEqual(upgraded["counters"]["observed_tool_calls"], 1)
        self.assertEqual(upgraded["task"]["transitions"][-1]["type"], "upgrade")

        downgraded = self.set_level("transition", 1, "Only a deterministic config edit remains.")["modules"]["task_level"]
        self.assertEqual(downgraded["counters"]["observed_tool_calls"], 1)
        self.assertEqual(downgraded["task"]["transitions"][-1]["type"], "downgrade")

        invalid = self.cli("level", "set", "--session-id", "transition", "--level", "9", "--reason", "invalid")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("Unknown Task Level", invalid.stderr)

    def test_replace_active_task_archives_the_previous_task(self) -> None:
        self.user_prompt("replace")
        original_id = self.task_level_state("replace")["task"]["id"]
        replacement = self.cli_json(
            "level", "begin", "--session-id", "replace", "--replace", "--reason", "The user changed the requested outcome."
        )["modules"]["task_level"]
        self.assertNotEqual(replacement["task"]["id"], original_id)
        self.assertEqual(replacement["task"]["level"], 1)
        self.assertEqual(replacement["task_history"][-1]["id"], original_id)
        self.assertEqual(replacement["task_history"][-1]["completion_reason"], "replaced")

    def test_l1_denies_a_subagent_in_the_vscode_format(self) -> None:
        self.user_prompt("deny")
        output = self.pre("deny", "runSubagent", SUBAGENT_INPUT)
        body = output["hookSpecificOutput"]
        self.assertEqual(body["hookEventName"], "PreToolUse")
        self.assertEqual(body["permissionDecision"], "deny")
        self.assertIn("Task Level 1", body["permissionDecisionReason"])
        self.assertNotIn("permissionDecision", output)  # the top-level format is ignored by VS Code (B1, R4a)

    def test_l2_also_denies_a_subagent(self) -> None:
        self.user_prompt("l2-deny")
        self.set_level("l2-deny", 2)
        self.assertEqual(self.pre("l2-deny", "runSubagent", SUBAGENT_INPUT)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_l3_limits_subagents_to_four(self) -> None:
        self.user_prompt("delegation")
        self.set_level("delegation", 3)
        for _ in range(4):
            self.assertEqual(self.pre("delegation", "runSubagent", SUBAGENT_INPUT), {})
        fifth = self.pre("delegation", "runSubagent", SUBAGENT_INPUT)
        self.assertEqual(fifth["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.task_level_state("delegation")["counters"]["subagents_created"], 4)

    def test_search_warning_uses_the_vscode_format(self) -> None:
        self.user_prompt("warn-format")
        self.pre("warn-format", "grep_search", GREP_INPUT)
        self.post("warn-format", "grep_search", GREP_INPUT)
        self.pre("warn-format", "grep_search", GREP_INPUT)
        warning = self.post("warn-format", "grep_search", GREP_INPUT)
        body = warning["hookSpecificOutput"]
        self.assertEqual(body["hookEventName"], "PostToolUse")
        self.assertIn("repository_searches", body["additionalContext"])
        self.assertIn("2/2", body["additionalContext"])

    def test_soft_search_warning_is_emitted_once(self) -> None:
        self.user_prompt("warning")
        self.pre("warning", "grep_search", GREP_INPUT)
        self.assertEqual(self.post("warning", "grep_search", GREP_INPUT), {})
        self.pre("warning", "grep_search", GREP_INPUT)
        self.assertIn("2/2", self.post("warning", "grep_search", GREP_INPUT)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.post("warning", "grep_search", GREP_INPUT), {})

    def test_all_search_tools_and_terminal_searches_are_counted(self) -> None:
        self.user_prompt("search-kinds")
        for tool in ("grep_search", "file_search", "semantic_search"):
            self.pre("search-kinds", tool, {"query": "x"})
        self.pre("search-kinds", "run_in_terminal", {"command": "git grep sandbox", "mode": "sync"})
        self.pre("search-kinds", "run_in_terminal", {"command": "echo hi && rg sandbox .", "mode": "sync"})
        self.pre("search-kinds", "run_in_terminal", {"command": "git status --short", "mode": "sync"})
        self.pre("search-kinds", "read_file", {"filePath": "/a/b.md"})
        counters = self.task_level_state("search-kinds")["counters"]
        self.assertEqual(counters["repository_searches"], 5)
        self.assertEqual(counters["observed_tool_calls"], 7)

    def test_the_level_cli_call_is_not_counted_or_denied(self) -> None:
        self.user_prompt("control")
        command = "python3 .harness/engine/cli.py level set --session-id control --level 2 --reason x"
        self.assertEqual(self.pre("control", "run_in_terminal", {"command": command, "mode": "sync"}), {})
        self.assertEqual(self.task_level_state("control")["counters"]["observed_tool_calls"], 0)

    def test_session_state_is_isolated_by_session(self) -> None:
        self.user_prompt("session-a")
        self.user_prompt("session-b")
        self.set_level("session-a", 3)
        self.assertEqual(self.task_level_state("session-a")["task"]["level"], 3)
        self.assertEqual(self.task_level_state("session-b")["task"]["level"], 1)
        self.assertTrue(self.state_file("session-a").exists())
        self.assertTrue(self.state_file("session-b").exists())

    def test_shared_level_mirrors_the_task_level(self) -> None:
        self.user_prompt("shared")
        self.set_level("shared", 2)
        self.assertEqual(self.session_state("shared")["level"], 2)
        self.cli_json("level", "complete", "--session-id", "shared", "--reason", "done")
        self.assertEqual(self.session_state("shared")["level"], 1)

    def test_concurrent_updates_do_not_lose_tool_counts(self) -> None:
        self.user_prompt("concurrent")
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(lambda _: self.pre("concurrent"), range(10)))
        self.assertEqual(results, [{}] * 10)
        self.assertEqual(self.task_level_state("concurrent")["counters"]["observed_tool_calls"], 10)

    def test_a_subagent_call_message_does_not_start_a_task(self) -> None:
        """Layer 1: the UserPromptSubmit text equals the allowed runSubagent prompt."""
        self.user_prompt("child-msg")
        self.set_level("child-msg", 3)
        self.assertEqual(self.pre("child-msg", "runSubagent", SUBAGENT_INPUT), {})
        self.cli_json("level", "complete", "--session-id", "child-msg", "--reason", "done")
        self.assertEqual(self.user_prompt("child-msg", SUBAGENT_INPUT["prompt"]), {})
        self.assertEqual(self.task_level_state("child-msg")["task"]["status"], "completed")
        # The same text typed by the user afterwards is a normal prompt again.
        self.assertIn("hookSpecificOutput", self.user_prompt("child-msg", SUBAGENT_INPUT["prompt"]))
        self.assertEqual(self.task_level_state("child-msg")["task"]["status"], "active")

    def test_a_prompt_inside_the_subagent_window_does_not_start_a_task(self) -> None:
        """Layer 2: anything that arrives between SubagentStart and SubagentStop is not the user."""
        self.user_prompt("window")
        self.cli_json("level", "complete", "--session-id", "window", "--reason", "done")
        self.hook(payload("SubagentStart", "window", agent_id="a1", agent_type="verifier"))
        self.assertEqual(self.user_prompt("window", "text the model wrote"), {})
        self.assertEqual(self.task_level_state("window")["task"]["status"], "completed")
        self.hook(payload("SubagentStop", "window", agent_id="a1", agent_type="verifier", stop_hook_active=False))
        self.assertIn("hookSpecificOutput", self.user_prompt("window", "now the user speaks"))
        self.assertEqual(self.task_level_state("window")["task"]["status"], "active")

    # --- fail-open ----------------------------------------------------------------------------

    def test_module_fails_open_when_the_policy_is_missing(self) -> None:
        missing = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, missing)
        make_root(missing, with_policy=False)
        self.env["HARNESS_ROOT"] = str(missing)
        self.assertEqual(self.pre("missing-policy"), {})
        errors = (missing / ".harness" / "runtime" / "logs" / "hook-errors.jsonl").read_text(encoding="utf-8")
        self.assertIn("module:task_level", errors)

    def test_hook_fails_open_when_the_registry_is_missing(self) -> None:
        missing = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, missing)
        make_root(missing, with_registry=False)
        self.env["HARNESS_ROOT"] = str(missing)
        self.assertEqual(self.pre("missing-registry"), {})
        self.assertTrue((missing / ".harness" / "runtime" / "logs" / "hook-errors.jsonl").exists())

    def test_hook_fails_open_for_corrupted_state(self) -> None:
        self.user_prompt("corrupt")
        self.state_file("corrupt").write_text("this is not json", encoding="utf-8")
        self.assertEqual(self.pre("corrupt"), {})
        self.assertTrue(self.log_lines("hook-errors.jsonl"))

    def test_hook_fails_open_for_bad_input(self) -> None:
        for text in ("", "not json", "[]", '{"hook_event_name": "PreToolUse"}', '{"unknown": 1}'):
            completed = self.run_script(HOOK, stdin=text)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(json.loads(completed.stdout), {})

    def test_a_failing_module_rolls_back_its_state_changes(self) -> None:
        self.user_prompt("rollback")
        state = json.loads(self.state_file("rollback").read_text(encoding="utf-8"))
        state["modules"]["task_level"]["counters"]["observed_tool_calls"] = -1  # invalid on purpose
        self.state_file("rollback").write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual(self.pre("rollback"), {})
        after = json.loads(self.state_file("rollback").read_text(encoding="utf-8"))
        self.assertEqual(after["modules"]["task_level"]["counters"]["observed_tool_calls"], -1)


if __name__ == "__main__":
    unittest.main()
