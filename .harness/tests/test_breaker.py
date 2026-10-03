"""Deny circuit breaker (B6, M3-4): the same deny repeated in one prompt window ends with a stop instruction."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List, Optional

from support import HarnessTestCase, payload, pre_tool

from core import breaker
from core.events import Decision, HookEvent
from core.state import update_state

GUARD = ".harness/policies/gate.json"


class BreakerUnitTests(unittest.TestCase):
    def event(self, name: str = "PreToolUse") -> HookEvent:
        return HookEvent(surface="vscode", event=name, session_id="s")

    def test_counts_by_reason_and_trips_at_the_limit(self) -> None:
        state: Dict[str, Any] = {}
        reasons = []
        for _ in range(4):
            decision = Decision(permission="deny", reason="same reason")
            from pathlib import Path

            info = breaker.apply(Path("/nowhere"), state, self.event(), decision, 1)  # no policy file: the default limit
            reasons.append((info["count"], info["tripped"], decision.reason))
        self.assertEqual([item[:2] for item in reasons], [(1, False), (2, False), (3, True), (4, True)])
        self.assertEqual(reasons[0][2], "same reason")
        self.assertIn("同一个拒绝已出现 3 次", reasons[2][2])
        self.assertIn("same reason", reasons[2][2])

    def test_other_decisions_are_not_counted(self) -> None:
        from pathlib import Path

        state: Dict[str, Any] = {}
        for decision, name in (
            (Decision(permission="ask", reason="r"), "PreToolUse"),
            (Decision(permission="allow"), "PreToolUse"),
            (Decision(block=True, reason="r"), "Stop"),
            (Decision(permission="deny", reason="r"), "PostToolUse"),
            (Decision(permission="deny", reason=""), "PreToolUse"),
            (Decision(context="hello"), "UserPromptSubmit"),
        ):
            self.assertIsNone(breaker.apply(Path("/nowhere"), state, self.event(name), decision, 1))
        self.assertEqual(state.get("denials", {}), {})

    def test_the_text_depends_on_the_level(self) -> None:
        self.assertNotIn("blocked", breaker.stop_text(3, "r", 1))
        self.assertIn("blocked", breaker.stop_text(3, "r", 3))
        self.assertIn("告诉用户", breaker.stop_text(3, "r", 1))
        self.assertIn("告诉用户", breaker.stop_text(3, "r", 3))


class BreakerHookTests(HarnessTestCase):
    session = "breaker-session"

    def setUp(self) -> None:
        super().setUp()
        self.base = str(self.root.resolve())

    def set_limit(self, limit: Optional[int]) -> None:
        path = self.root / ".harness" / "policies" / "gate.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if limit is None:
            data.pop("circuit_breaker", None)
        else:
            data["circuit_breaker"] = {"repeat_limit": limit}
        path.write_text(json.dumps(data), encoding="utf-8")

    def prompt(self, text: str = "work", session: Optional[str] = None) -> None:
        self.hook(payload("UserPromptSubmit", session or self.session, prompt=text))

    def tool(self, tool: str, tool_input: dict, session: Optional[str] = None) -> Dict[str, Any]:
        data = pre_tool(session or self.session, tool, tool_input)
        data["cwd"] = self.base
        return self.hook(data)

    def denied_write(self, relative: str = GUARD, session: Optional[str] = None) -> str:
        output = self.tool("create_file", {"filePath": f"{self.base}/{relative}", "content": ""}, session)
        body = output["hookSpecificOutput"]
        self.assertEqual(body["permissionDecision"], "deny")
        return body["permissionDecisionReason"]

    def test_the_third_identical_deny_becomes_a_stop_instruction(self) -> None:
        self.prompt()
        first, second, third, fourth = (self.denied_write() for _ in range(4))
        self.assertIn("guardrail", first)
        self.assertEqual(first, second)
        self.assertIn("同一个拒绝已出现 3 次", third)
        self.assertIn("停止重试", third)
        self.assertIn(GUARD, third)  # the original reason is still there for the user
        self.assertIn("同一个拒绝已出现 4 次", fourth)

    def test_different_reasons_do_not_add_up(self) -> None:
        self.prompt()
        for _ in range(3):
            self.assertIn("guardrail", self.denied_write(GUARD))
            self.assertIn("guardrail", self.denied_write(".harness/registry.json"))
        # Each reason has been seen three times by now, and each tripped on its own third call.
        self.assertIn("同一个拒绝", self.denied_write(GUARD))

    def test_a_new_user_prompt_starts_a_new_window(self) -> None:
        self.prompt()
        for _ in range(3):
            self.denied_write()
        self.prompt("another task")
        self.assertIn("guardrail", self.denied_write())
        self.assertNotIn("同一个拒绝", self.denied_write())

    def test_a_subagent_message_or_a_stop_continuation_does_not_open_a_new_window(self) -> None:
        self.prompt()
        for _ in range(2):
            self.denied_write()
        self.hook(payload("SubagentStart", self.session, agent_id="a1", agent_type="verifier"))
        self.hook(payload("UserPromptSubmit", self.session, prompt="you are the verifier"))  # the call message
        self.assertIn("同一个拒绝已出现 3 次", self.denied_write())

    def test_the_limit_comes_from_the_policy(self) -> None:
        self.set_limit(2)
        self.prompt()
        self.assertIn("guardrail", self.denied_write())
        self.assertIn("同一个拒绝已出现 2 次", self.denied_write())

    def test_a_limit_of_zero_turns_the_breaker_off(self) -> None:
        self.set_limit(0)
        self.prompt()
        for _ in range(6):
            self.assertNotIn("同一个拒绝", self.denied_write())

    def test_a_missing_limit_uses_the_default(self) -> None:
        self.set_limit(None)
        self.prompt()
        self.denied_write()
        self.denied_write()
        self.assertIn("同一个拒绝已出现 3 次", self.denied_write())

    def test_it_covers_denies_of_any_module(self) -> None:
        # task_level: the L1 search budget is two; the third and later searches are denied with the same reason.
        self.prompt()
        self.assertEqual(self.tool("grep_search", {"query": "a"}), {})
        self.assertEqual(self.tool("grep_search", {"query": "b"}), {})
        reasons: List[str] = [self.tool("grep_search", {"query": "c"})["hookSpecificOutput"]["permissionDecisionReason"] for _ in range(3)]
        self.assertIn("探索预算已用完", reasons[0])
        self.assertIn("探索预算已用完", reasons[1])
        self.assertIn("同一个拒绝已出现 3 次", reasons[2])
        self.assertIn("探索预算已用完", reasons[2])  # the original text is kept inside

    def test_the_text_for_l3_mentions_the_blocked_handoff(self) -> None:
        self.prompt()
        update_state(self.root, "vscode", self.session, lambda state: state.update(active_request="req-1"))
        reason = ""
        for _ in range(3):
            reason = self.denied_write("README.md")  # outside the request folder
        self.assertIn("同一个拒绝已出现 3 次", reason)
        self.assertIn("blocked", reason)

    def test_ask_is_not_counted(self) -> None:
        self.prompt()
        for _ in range(5):
            output = self.tool("run_in_terminal", {"command": "git push"})
            self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "ask")
            self.assertNotIn("同一个拒绝", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_the_log_records_the_count_and_the_trip(self) -> None:
        self.prompt()
        for _ in range(3):
            self.denied_write()
        denials = [item["denial"] for item in self.call_lines() if "denial" in item]
        self.assertEqual([item["count"] for item in denials], [1, 2, 3])
        self.assertEqual([item["tripped"] for item in denials], [False, False, True])
        self.assertEqual(len({item["reason_hash"] for item in denials}), 1)

    def test_a_subagent_session_counts_on_its_own(self) -> None:
        # Copilot SDK engine: the subagent has a session of its own, so its retries add up apart from the parent's.
        def sdk(session: str) -> Dict[str, Any]:
            data = {"hook_event_name": "PreToolUse", "session_id": session, "timestamp": "2026-10-02T00:00:00.000Z", "cwd": self.base,
                    "tool_name": "Write", "tool_input": {"path": f"{self.base}/{GUARD}", "file_text": "{}"}}
            return self.hook(data)

        self.assertIn("guardrail", sdk("sdk-main")["permissionDecisionReason"])
        self.assertIn("guardrail", sdk("sdk-child")["permissionDecisionReason"])
        self.assertIn("guardrail", sdk("sdk-child")["permissionDecisionReason"])
        self.assertIn("同一个拒绝已出现 3 次", sdk("sdk-child")["permissionDecisionReason"])
        self.assertNotIn("同一个拒绝", sdk("sdk-main")["permissionDecisionReason"])  # the parent has only seen two

    def test_a_broken_breaker_leaves_the_deny_in_place(self) -> None:
        (self.root / ".harness" / "policies" / "gate.json").write_text("{ broken", encoding="utf-8")
        self.prompt()
        # gate itself fails open on a broken policy, so use the budget deny of task_level to get a deny.
        self.tool("grep_search", {"query": "a"})
        self.tool("grep_search", {"query": "b"})
        output = self.tool("grep_search", {"query": "c"})
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
