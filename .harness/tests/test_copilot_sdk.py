"""The Copilot SDK engine (recorded 2026-10-01): tool names, subagent sessions, and the top-level output format."""

from __future__ import annotations

import json
import time
import unittest
from typing import Any, Dict, List, Optional

from support import REPO, HarnessTestCase

import hook
from adapters import copilot_vscode
from core import state

FIXTURES = REPO / ".harness" / "eval" / "fixtures" / "hooks" / "copilot-sdk"
PARENT = "session-parent-verifier"
CHILD = "session-child-verifier"


def recorded(name: str) -> List[Dict[str, Any]]:
    with (FIXTURES / "sessions" / name).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def ev(data: Dict[str, Any]) -> Any:
    return copilot_vscode.event_name(data)


def sid(data: Dict[str, Any]) -> Any:
    return data.get("session_id") or data.get("sessionId")


def sample(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / "payloads" / name).read_text(encoding="utf-8"))


class SdkTestCase(HarnessTestCase):
    def feed(self, data: Dict[str, Any]) -> tuple:
        return hook.process(json.dumps(data), self.root)

    def replay(self, name: str, drop: Optional[Any] = None, edit: Optional[Any] = None) -> List[tuple]:
        results = []
        for data in recorded(name):
            if drop and drop(data):
                continue
            if edit:
                data = edit(data)
            output, record = self.feed(data)
            results.append((data, output, record))
        return results

    def module_state(self, session_id: str) -> Dict[str, Any]:
        return state.read_state(state.state_path(self.root, "vscode", session_id), "vscode", session_id)["modules"]["task_level"]

    def session(self, session_id: str) -> Dict[str, Any]:
        return state.read_state(state.state_path(self.root, "vscode", session_id), "vscode", session_id)


class EngineDetectionTests(unittest.TestCase):
    def test_every_recorded_sdk_payload_parses(self) -> None:
        for path in sorted((FIXTURES / "payloads").glob("*.json")):
            with self.subTest(path.name):
                event = copilot_vscode.parse(json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(event.surface, "vscode")

    def test_the_recorded_tool_names_have_the_right_kinds(self) -> None:
        kinds = {
            "Bash": "terminal", "Read": "read", "Write": "create", "Edit": "edit", "Grep": "search",
            "Glob": "search", "Agent": "subagent", "search_code_subagent": "search",
        }
        for name, kind in kinds.items():
            with self.subTest(name):
                event = copilot_vscode.parse(sample(f"PreToolUse.{name}.json"))
                self.assertEqual(event.tool_kind, kind)

    def test_agent_target_and_prompt_come_from_agent_type_and_prompt(self) -> None:
        event = copilot_vscode.parse(sample("PreToolUse.Agent.json"))
        self.assertEqual(event.subagent_target, "verifier")
        self.assertIn("复核", event.subagent_prompt)

    def test_a_result_is_read_from_tool_result(self) -> None:
        event = copilot_vscode.parse(sample("PostToolUse.Agent.json"))
        self.assertTrue(event.tool_response.startswith("VERDICT: PASS"))

    def test_subagent_start_has_no_event_name_and_is_camel_case(self) -> None:
        data = sample("SubagentStart.json")
        self.assertNotIn("hook_event_name", data)
        event = copilot_vscode.parse(data)
        self.assertEqual((event.event, event.agent_type, event.session_id), ("SubagentStart", "verifier", data["sessionId"]))

    def test_the_engine_is_told_from_the_payload(self) -> None:
        self.assertEqual(copilot_vscode.engine(sample("PreToolUse.Bash.json")), "cli")
        self.assertEqual(copilot_vscode.engine(sample("Stop.json")), "cli")
        self.assertEqual(copilot_vscode.engine(sample("SubagentStart.json")), "cli")
        # A subagent's own tools carry the legacy names and no other sign.
        self.assertEqual(copilot_vscode.engine(sample("PreToolUse.file_search.json")), "unknown")
        self.assertEqual(copilot_vscode.engine({"hook_event_name": "PreToolUse", "tool_use_id": "t1", "tool_name": "x"}), "legacy")


class OutputFormatTests(SdkTestCase):
    def test_deny_is_top_level_on_the_sdk_engine(self) -> None:
        self.feed({**sample("UserPromptSubmit.json"), "session_id": PARENT, "prompt": "[L2] change it"})
        agent = sample("PreToolUse.Agent.json")
        agent["session_id"] = PARENT
        output, _ = self.feed(agent)
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("[verify]", output["permissionDecisionReason"])
        self.assertNotIn("hookSpecificOutput", output)

    def test_deny_with_no_engine_sign_carries_both_formats(self) -> None:
        self.feed({**sample("UserPromptSubmit.json"), "session_id": "s", "prompt": "[L1] x"})
        data = {"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "runSubagent",
                "tool_input": {"agentName": "builder", "prompt": "p"}}
        output, _ = self.feed(data)
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_stop_block_is_top_level_on_the_sdk_engine(self) -> None:
        self.verifier_default(True)
        self.replay(
            "cli-verifier-call.jsonl",
            drop=lambda d: ev(d) in ("Stop",) or d.get("tool_name") in ("Agent", "Bash") or "agentName" in d
            or sid(d) == CHILD or ev(d) == "SubagentStop",
        )
        output, _ = self.feed(sample("Stop.json") | {"session_id": PARENT})
        self.assertEqual(output["decision"], "block")
        self.assertIn("改了文件", output["reason"])
        self.assertNotIn("hookSpecificOutput", output)

    def test_context_for_a_prompt_is_top_level(self) -> None:
        output, _ = self.feed({**sample("UserPromptSubmit.json"), "session_id": "fresh", "prompt": "hello"})
        self.assertIn("Task Level", output["additionalContext"])


class SubagentSessionTests(SdkTestCase):
    def test_the_recorded_verifier_call_ends_clean(self) -> None:
        self.verifier_default(False)
        results = self.replay("cli-verifier-call.jsonl")
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])
        parent = self.module_state(PARENT)
        self.assertEqual(parent["prompt"]["verify"], "on")
        self.assertEqual(parent["prompt"]["edits"], 1)  # the Write
        self.assertEqual(parent["counters"]["subagents_created"], 1)
        self.assertEqual([r["verdict"] for r in parent["reviews"]], ["PASS"])  # read from tool_result
        stops = [out for data, out, _ in results if ev(data) == "Stop"]
        self.assertEqual(stops, [{}, {}])  # the child's Stop and the parent's Stop: the review is done

    def test_the_child_session_is_linked_to_the_parent(self) -> None:
        self.replay("cli-verifier-call.jsonl")
        child = self.session(CHILD)
        self.assertEqual(child["parent_session_id"], PARENT)
        self.assertEqual(child["level"], 2)
        parent = self.session(PARENT)
        self.assertEqual(parent["subagents"]["active"], [])

    def test_the_child_call_message_is_not_a_user_prompt(self) -> None:
        results = self.replay("cli-verifier-call.jsonl")
        prompts = [(sid(data), record["from_subagent"], out) for data, out, record in results
                   if ev(data) == "UserPromptSubmit"]
        self.assertEqual(prompts[0][1:], (False, prompts[0][2]))
        self.assertIn("additionalContext", prompts[0][2])
        self.assertEqual(prompts[1], (CHILD, True, {}))  # no rules for the subagent, no new budget window
        self.assertEqual(self.module_state(PARENT)["prompt"]["count"], 1)

    def test_the_child_has_its_own_counts_and_no_budget(self) -> None:
        self.replay("cli-tools-and-search-subagent.jsonl")
        child = self.module_state("session-child-search")
        parent = self.module_state("session-parent-tools")
        self.assertEqual(child["counters"]["repository_searches"], 2)
        extra = {"hook_event_name": "PreToolUse", "session_id": "session-child-search", "tool_name": "grep_search", "tool_input": {"query": "x"}}
        for _ in range(3):  # past the L1 limit of two searches: the subagent has no budget
            self.assertEqual(self.feed(extra)[0], {})
        self.assertEqual(self.module_state("session-child-search")["counters"]["repository_searches"], 5)
        self.assertEqual(parent["counters"]["repository_searches"], 2)  # Grep and Glob; the search subagent was the third and is denied at L1
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])

    def test_a_search_inside_the_child_is_never_denied(self) -> None:
        results = self.replay("cli-tools-and-search-subagent.jsonl")
        child_denies = [out for data, out, _ in results if sid(data) == "session-child-search" and out.get("permissionDecision")]
        self.assertEqual(child_denies, [])

    def test_the_main_agent_third_search_is_still_denied_at_l1(self) -> None:
        results = self.replay("cli-tools-and-search-subagent.jsonl")
        # The recording has Grep, Glob and the search subagent: the third search is the subagent and L1 allows two.
        denied = [data["tool_name"] for data, out, _ in results if out.get("permissionDecision") == "deny"]
        self.assertEqual(denied, ["search_code_subagent"])

    def test_a_new_user_session_is_not_taken_for_a_child_without_a_waiting_parent(self) -> None:
        output, record = self.feed({**sample("UserPromptSubmit.json"), "session_id": "someone-else", "prompt": "hi"})
        self.assertFalse(record["from_subagent"])
        self.assertNotIn("parent_session_id", self.session("someone-else"))

    def test_an_old_waiting_parent_does_not_claim_a_new_session(self) -> None:
        self.replay("cli-verifier-call.jsonl", drop=lambda d: sid(d) == CHILD or ev(d) in ("SubagentStop", "Stop"))

        def age(current: Dict[str, Any]) -> None:
            for entry in current["subagents"]["active"]:
                entry["at"] = time.time() - 120

        state.update_state(self.root, "vscode", PARENT, age)
        _, record = self.feed({**sample("UserPromptSubmit.json"), "session_id": "late", "prompt": "unrelated"})
        self.assertFalse(record["from_subagent"])

    def test_subagent_stop_removes_the_waiting_entry(self) -> None:
        self.replay("cli-verifier-call.jsonl", drop=lambda d: sid(d) == CHILD)
        self.assertEqual(self.session(PARENT)["subagents"]["active"], [])

    def test_level_set_is_denied_for_a_subagent_too(self) -> None:
        self.replay("cli-verifier-call.jsonl", drop=lambda d: ev(d) in ("Stop", "SubagentStop"))
        data = {"hook_event_name": "PreToolUse", "session_id": CHILD, "tool_name": "Bash",
                "tool_input": {"command": "python3 .harness/engine/cli.py level set --session-id x --level 1"}}
        output, _ = self.feed(data)
        self.assertEqual(output["permissionDecision"], "deny")


class RecordedScenarioTests(SdkTestCase):
    """The B5 scenarios that failed on 2026-10-01 because the tool names were not known."""

    def test_s2_a_write_without_a_review_blocks_the_stop(self) -> None:
        self.replay("cli-verifier-call.jsonl", drop=lambda d: d.get("tool_name") == "Agent" or ev(d) in ("SubagentStart", "SubagentStop")
                    or sid(d) == CHILD or ev(d) == "Stop")
        output, _ = self.feed({"hook_event_name": "Stop", "session_id": PARENT, "stop_reason": "end_turn", "stop_hook_active": False})
        self.assertEqual(output["decision"], "block")

    def test_s4_level_set_in_bash_is_denied(self) -> None:
        self.feed({**sample("UserPromptSubmit.json"), "session_id": "s4", "prompt": "[L2] go"})
        data = {"hook_event_name": "PreToolUse", "session_id": "s4", "tool_name": "Bash",
                "tool_input": {"command": "python3 .harness/engine/cli.py level set --session-id test --level 1"}}
        output, _ = self.feed(data)
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("只有用户能切换 Level", output["permissionDecisionReason"])

    def test_s7_the_verifier_is_refused_when_the_review_is_off(self) -> None:
        self.verifier_default(False)

        def no_marker(data: Dict[str, Any]) -> Dict[str, Any]:
            if ev(data) == "UserPromptSubmit" and sid(data) == PARENT:
                data = {**data, "prompt": data["prompt"].replace("[verify] ", "")}
            return data

        results = self.replay("cli-verifier-call.jsonl", edit=no_marker, drop=lambda d: sid(d) == CHILD)
        denied = [out for data, out, _ in results if data.get("tool_name") == "Agent" and ev(data) == "PreToolUse"]
        self.assertEqual(denied[0]["permissionDecision"], "deny")
        self.assertIn("没有开启 verifier 复核", denied[0]["permissionDecisionReason"])

    def test_the_semantic_search_subagent_is_not_blocked_as_a_subagent_at_l2(self) -> None:
        self.feed({**sample("UserPromptSubmit.json"), "session_id": "s-search", "prompt": "[L2] find it"})
        data = {"hook_event_name": "PreToolUse", "session_id": "s-search", "tool_name": "search_code_subagent", "tool_input": {"query": "x"}}
        output, _ = self.feed(data)
        self.assertEqual(output, {})


class ContinuationTests(SdkTestCase):
    """The SDK engine feeds the reason of a Stop block back as a new UserPromptSubmit. It must not reset the prompt."""

    def blocked_session(self, sid: str = "cont") -> str:
        self.feed({**sample("UserPromptSubmit.json"), "session_id": sid, "prompt": "[L2] [verify] change a file"})
        self.feed({"hook_event_name": "PostToolUse", "session_id": sid, "tool_name": "Write",
                   "tool_input": {"path": "/w/a.txt", "file_text": "x"}, "tool_result": {"result_type": "success", "text_result_for_llm": "ok"}})
        output, _ = self.feed({"hook_event_name": "Stop", "session_id": sid, "stop_reason": "end_turn", "stop_hook_active": False})
        self.assertEqual(output["decision"], "block")
        return output["reason"]

    def test_the_fed_back_reason_is_not_a_new_prompt(self) -> None:
        reason = self.blocked_session()
        output, record = self.feed({**sample("UserPromptSubmit.json"), "session_id": "cont", "prompt": reason})
        self.assertEqual(output, {})  # no rules injected again
        self.assertTrue(record["continuation"])
        prompt = self.module_state("cont")["prompt"]
        self.assertEqual((prompt["count"], prompt["edits"], prompt["verify"]), (1, 1, "on"))

    def test_the_verifier_can_then_be_called_and_the_stop_passes(self) -> None:
        reason = self.blocked_session()
        self.feed({**sample("UserPromptSubmit.json"), "session_id": "cont", "prompt": reason})
        agent = {"hook_event_name": "PreToolUse", "session_id": "cont", "tool_name": "Agent",
                 "tool_input": {"name": "v", "agent_type": "verifier", "prompt": "check", "mode": "sync"}}
        self.assertEqual(self.feed(agent)[0], {})
        done = {"hook_event_name": "PostToolUse", "session_id": "cont", "tool_name": "Agent", "tool_input": agent["tool_input"],
                "tool_result": {"result_type": "success", "text_result_for_llm": "VERDICT: PASS\nok"}}
        self.feed(done)
        output, _ = self.feed({"hook_event_name": "Stop", "session_id": "cont", "stop_reason": "end_turn", "stop_hook_active": True})
        self.assertEqual(output, {})

    def test_a_real_next_prompt_still_starts_a_new_window(self) -> None:
        self.blocked_session()
        output, record = self.feed({**sample("UserPromptSubmit.json"), "session_id": "cont", "prompt": "something else"})
        self.assertFalse(record["continuation"])
        self.assertIn("additionalContext", output)
        self.assertEqual(self.module_state("cont")["prompt"]["count"], 2)

    def test_the_reason_is_only_matched_once(self) -> None:
        reason = self.blocked_session()
        self.feed({**sample("UserPromptSubmit.json"), "session_id": "cont", "prompt": reason})
        _, record = self.feed({**sample("UserPromptSubmit.json"), "session_id": "cont", "prompt": reason})
        self.assertFalse(record["continuation"])


class SubagentStopBlockTests(SdkTestCase):
    def test_a_block_reason_fed_to_the_subagent_is_not_a_user_prompt(self) -> None:
        results = self.replay("cli-subagent-stop-block.jsonl")
        child_prompts = [(out, record) for data, out, record in results
                         if ev(data) == "UserPromptSubmit" and sid(data) == "session-child-stopblock"]
        self.assertEqual(len(child_prompts), 2)  # the call message, then the reason of the SubagentStop block
        for out, record in child_prompts:
            self.assertTrue(record["from_subagent"])
            self.assertEqual(out, {})  # no rules injected into the subagent
        self.assertEqual(self.session("session-child-stopblock")["parent_session_id"], "session-parent-stopblock")
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])


class GenericSubagentTests(SdkTestCase):
    def test_a_built_in_agent_type_is_denied_with_the_allowed_list(self) -> None:
        self.feed({**sample("UserPromptSubmit.json"), "session_id": "g", "prompt": "[L2] [verify] read it"})
        agent = {"hook_event_name": "PreToolUse", "session_id": "g", "tool_name": "Agent",
                 "tool_input": {"name": "x", "agent_type": "explore", "prompt": "read", "mode": "sync"}}
        output, _ = self.feed(agent)
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("只允许这些子 agent：verifier", output["permissionDecisionReason"])
        self.assertIn("explore", output["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
