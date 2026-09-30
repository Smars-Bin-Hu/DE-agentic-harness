"""Replay the real VS Code recordings (B1) through hook.py."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List

from support import FIXTURES, HOOK, HarnessTestCase, iter_session, load_payload

import hook
from core import config, state
from modules.task_level import lifecycle

SESSIONS = sorted(path.name for path in (FIXTURES / "sessions").glob("*.jsonl"))


def deny_reason(output: Dict[str, Any]) -> str:
    return output.get("hookSpecificOutput", {}).get("permissionDecision", "")


class ReplayTests(HarnessTestCase):
    def feed(self, data: Dict[str, Any]) -> tuple:
        return hook.process(json.dumps(data), self.root)

    def replay(self, name: str, set_level: int = 0, before_event: str = "") -> List[tuple]:
        """Feed a recorded session in order. Optionally set the task level right after the first prompt."""
        results = []
        leveled = False
        for data in iter_session(name):
            if set_level and not leveled and data["hook_event_name"] == before_event:
                session_id = data["session_id"]
                policy = config.load_policy(self.root, "task-levels")

                def raise_level(current: dict) -> None:
                    ms = lifecycle.ensure_module_state(current, "task_level")
                    lifecycle.set_level(ms, set_level, "test", policy)
                    lifecycle.sync_shared_level(current, ms)

                state.update_state(self.root, "vscode", session_id, raise_level)
                leveled = True
            results.append((data, *self.feed(data)))
        return results

    def test_every_session_replays_without_a_hook_error(self) -> None:
        for name in SESSIONS:
            with self.subTest(name):
                results = self.replay(name)
                self.assertEqual(len(results), len(list(iter_session(name))))
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])

    def test_every_single_payload_is_handled(self) -> None:
        for path in sorted((FIXTURES / "payloads").glob("*.json")):
            with self.subTest(path.name):
                self.feed(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])

    def test_l1_denies_the_recorded_subagent_calls(self) -> None:
        for name in ("subagent-child.jsonl", "subagent-default-to-locked.jsonl"):
            with self.subTest(name):
                calls = [
                    (data, output)
                    for data, output, _ in self.replay(name)
                    if data["hook_event_name"] == "PreToolUse" and data["tool_name"] == "runSubagent"
                ]
                self.assertEqual(len(calls), 1)
                data, output = calls[0]
                self.assertEqual(deny_reason(output), "deny")
                self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PreToolUse")
                self.assertIn("Task Level 1", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_l3_allows_the_subagent_and_flags_its_call_message(self) -> None:
        results = self.replay("subagent-child.jsonl", set_level=3, before_event="PreToolUse")
        by_event = [(data["hook_event_name"], data.get("tool_name", ""), output, record) for data, output, record in results]
        run = next(item for item in by_event if item[0] == "PreToolUse" and item[1] == "runSubagent")
        self.assertEqual(run[2], {})
        prompts = [item for item in by_event if item[0] == "UserPromptSubmit"]
        self.assertEqual([item[3]["from_subagent"] for item in prompts], [False, True])
        self.assertEqual(prompts[1][2], {})  # no context injected into the subagent, no new task
        # Tool events inside the subagent are counted like any other, and nothing is left open afterwards.
        final = state.read_state(state.state_path(self.root, "vscode", "session-subagent-child"), "vscode", "session-subagent-child")
        self.assertEqual(final["subagents"], {"active": [], "pending_prompts": []})
        self.assertEqual(final["modules"]["task_level"]["counters"]["subagents_created"], 1)

    def test_the_recorded_call_message_is_recognized_by_text_alone(self) -> None:
        """Layer 1 on real data: drop SubagentStart so only the text match can flag the child prompt."""
        results = list(iter_session("subagent-child.jsonl"))
        session_id = results[0]["session_id"]
        flags = []
        policy = config.load_policy(self.root, "task-levels")
        for data in results:
            if data["hook_event_name"] in ("SubagentStart", "SubagentStop"):
                continue
            if data["hook_event_name"] == "PreToolUse" and data["tool_name"] == "runSubagent":

                def raise_level(current: dict) -> None:
                    ms = lifecycle.ensure_module_state(current, "task_level")
                    lifecycle.set_level(ms, 3, "test", policy)

                state.update_state(self.root, "vscode", session_id, raise_level)
            _, record = self.feed(data)
            if data["hook_event_name"] == "UserPromptSubmit":
                flags.append(record["from_subagent"])
        self.assertEqual(flags, [False, True])

    def test_tool_counts_match_the_recording(self) -> None:
        for name in ("tools-basic.jsonl", "tools-edit-list-search.jsonl"):
            with self.subTest(name):
                self.replay(name)
                events = list(iter_session(name))
                session_id = events[0]["session_id"]
                pre = [e for e in events if e["hook_event_name"] == "PreToolUse"]
                searches = [e for e in pre if e["tool_name"] in ("grep_search", "file_search", "semantic_search")]
                counters = self.task_level_state(session_id)["counters"]
                self.assertEqual(counters["observed_tool_calls"], len(pre))
                self.assertEqual(counters["repository_searches"], len(searches))

    def test_stop_and_subagent_events_are_accepted_and_silent(self) -> None:
        for name in ("stop-block-once.jsonl", "subagent-child.jsonl"):
            for data, output, record in self.replay(name):
                if data["hook_event_name"] in ("Stop", "SubagentStart", "SubagentStop"):
                    self.assertEqual(output, {})
                    self.assertEqual(record["modules"], [])  # task_level does not subscribe to these yet

    def test_the_marker_session_with_leading_fence_replays(self) -> None:
        results = self.replay("prompt-l2-marker.jsonl")
        prompt = next(data["prompt"] for data, _, _ in results if data["hook_event_name"] == "UserPromptSubmit")
        self.assertIn("[L2]", prompt)


class ReplayThroughTheRealProcessTests(HarnessTestCase):
    """One process per event, as VS Code runs it: one call record per event, in order."""

    def test_each_event_leaves_exactly_one_call_record(self) -> None:
        events = list(iter_session("subagent-child.jsonl"))
        for data in events:
            self.hook(data)
        calls = self.log_lines("hook-calls.jsonl")
        self.assertEqual([c["event"] for c in calls], [e["hook_event_name"] for e in events])
        self.assertEqual(len({c["pid"] for c in calls}), len(events))
        self.assertTrue(all("error" not in c for c in calls))
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])
        self.assertTrue(all(c["ms"] < 300 for c in calls), [c["ms"] for c in calls])

    def test_the_recorded_denied_call_leaves_a_deny_record(self) -> None:
        for data in iter_session("subagent-default-to-locked.jsonl"):
            self.hook(data)
        denied = [c for c in self.log_lines("hook-calls.jsonl") if c["decision"] == "deny"]
        self.assertEqual([c["tool_name"] for c in denied], ["runSubagent"])

    def test_the_output_of_a_recorded_payload_is_valid_json_with_ascii_only(self) -> None:
        completed = self.run_script(HOOK, stdin=json.dumps(load_payload("UserPromptSubmit.json")))
        completed.stdout.encode("ascii")  # Chinese text is escaped, so any console encoding can carry it
        self.assertIn("hookSpecificOutput", json.loads(completed.stdout))


if __name__ == "__main__":
    unittest.main()
