"""Replay the real VS Code recordings (B1) through hook.py."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List

from support import FIXTURES, HOOK, HarnessTestCase, iter_session, load_payload

import hook
from core import state

SESSIONS = sorted(path.name for path in (FIXTURES / "sessions").glob("*.jsonl"))


def rename_agent(data: Dict[str, Any], agent: str) -> Dict[str, Any]:
    if not agent:
        return data
    data = json.loads(json.dumps(data))
    if "agent_type" in data:
        data["agent_type"] = agent
    if data.get("tool_name") == "runSubagent":
        data["tool_input"]["agentName"] = agent
    return data


def deny_reason(output: Dict[str, Any]) -> str:
    return output.get("hookSpecificOutput", {}).get("permissionDecision", "")


class ReplayTests(HarnessTestCase):
    def feed(self, data: Dict[str, Any]) -> tuple:
        return hook.process(json.dumps(data), self.root)

    def replay(self, name: str, set_level: int = 0, before_event: str = "", agent: str = "") -> List[tuple]:
        """Feed a recorded session in order. Optionally set the level before `before_event`.

        `agent` renames the recorded subagent (`probe-child`), so the replay can pass a level's allow list.
        """
        results = []
        leveled = False
        for data in iter_session(name):
            data = rename_agent(data, agent)
            if set_level and not leveled and data["hook_event_name"] == before_event:
                # Level 3 is entered through a request, so a running request stands in for it.
                def raise_level(current: dict) -> None:
                    if set_level == 3:
                        current["active_request"] = "req-test"
                    else:
                        current["level"] = set_level

                state.update_state(self.root, "vscode", data["session_id"], raise_level)
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
                self.assertIn("L1 不允许子 agent", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_an_allowed_subagent_passes_and_its_call_message_is_flagged(self) -> None:
        for level, agent in ((2, "verifier"), (3, "builder")):
            with self.subTest(level=level):
                self.setUp()
                self.verifier_default(True)
                results = self.replay("subagent-child.jsonl", set_level=level, before_event="PreToolUse", agent=agent)
                by_event = [
                    (data["hook_event_name"], data.get("tool_name", ""), output, record) for data, output, record in results
                ]
                run = next(item for item in by_event if item[0] == "PreToolUse" and item[1] == "runSubagent")
                self.assertEqual(run[2], {})
                prompts = [item for item in by_event if item[0] == "UserPromptSubmit"]
                self.assertEqual([item[3]["from_subagent"] for item in prompts], [False, True])
                self.assertEqual(prompts[1][2], {})  # nothing injected into the subagent, no new budget window
                # Tool events inside the subagent are counted like any other, and nothing is left open afterwards.
                sid = "session-subagent-child"
                final = state.read_state(state.state_path(self.root, "vscode", sid), "vscode", sid)
                self.assertEqual(final["subagents"], {"active": [], "pending_prompts": []})
                self.assertEqual(final["modules"]["task_level"]["counters"]["subagents_created"], 1)
                self.assertEqual(final["modules"]["task_level"]["prompt"]["count"], 1)

    def test_the_recorded_subagent_name_is_not_on_any_allow_list(self) -> None:
        results = self.replay("subagent-child.jsonl", set_level=2, before_event="PreToolUse")
        run = next(out for data, out, _ in results if data.get("tool_name") == "runSubagent" and data["hook_event_name"] == "PreToolUse")
        self.assertEqual(deny_reason(run), "deny")
        self.assertIn("verifier", run["hookSpecificOutput"]["permissionDecisionReason"])

    def test_the_recorded_call_message_is_recognized_by_text_alone(self) -> None:
        """Layer 1 on real data: drop SubagentStart so only the text match can flag the child prompt."""
        self.verifier_default(True)
        results = list(iter_session("subagent-child.jsonl"))
        session_id = results[0]["session_id"]
        flags = []
        for data in results:
            if data["hook_event_name"] in ("SubagentStart", "SubagentStop"):
                continue
            data = rename_agent(data, "verifier")
            if data["hook_event_name"] == "PreToolUse" and data["tool_name"] == "runSubagent":
                state.update_state(self.root, "vscode", session_id, lambda current: current.update(level=2))
            _, record = self.feed(data)
            if data["hook_event_name"] == "UserPromptSubmit":
                flags.append(record["from_subagent"])
        self.assertEqual(flags, [False, True])

    def test_tool_counts_match_the_recording(self) -> None:
        for name in ("tools-basic.jsonl", "tools-edit-list-search.jsonl"):
            with self.subTest(name):
                self.replay(name, set_level=2, before_event="PreToolUse")  # L1 would deny the third search
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
                    self.assertEqual(output, {})  # L1: nothing to review
                    # task_level handles Stop (L2 review check). The request module listens to SubagentStart (it has nothing to say at L1).
                    expected = {"Stop": ["task_level"], "SubagentStart": ["request"], "SubagentStop": []}
                    self.assertEqual(record["modules"], expected[data["hook_event_name"]])

    def test_the_recorded_pasted_marker_switches_to_l2(self) -> None:
        """The recorded prompt starts with a markdown code fence (a paste artifact), then `[L2]`."""
        results = self.replay("prompt-l2-marker.jsonl")
        prompt = next(data["prompt"] for data, _, _ in results if data["hook_event_name"] == "UserPromptSubmit")
        self.assertTrue(prompt.startswith("```"))
        self.assertEqual(self.session_state("session-prompt-l2-marker")["level"], 2)
        self.assertEqual(self.task_level_state("session-prompt-l2-marker")["level_changes"][-1]["source"], "marker")


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
        self.assertIn("additionalContext", json.loads(completed.stdout))


if __name__ == "__main__":
    unittest.main()
