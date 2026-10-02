"""L2 review (B5): verdict parsing, edit tracking, and the Stop check, one test per branch."""

from __future__ import annotations

import json
import unittest
from typing import Optional

from support import HarnessTestCase, load_payload, payload, post_tool, pre_tool

from modules.task_level import review

VERIFIER = {"agentName": "verifier", "prompt": "check it", "description": "check"}
EDIT = {"filePath": "/w/a.txt", "oldString": "a", "newString": "b"}
GREP = {"query": "x"}


class VerdictTests(unittest.TestCase):
    def test_the_first_line_decides(self) -> None:
        cases = {
            "VERDICT: PASS": "PASS",
            "VERDICT: FAIL\n- tests fail": "FAIL",
            "verdict: pass": "PASS",
            "VERDICT：PASS": "PASS",  # full-width colon
            "**VERDICT: FAIL**": "FAIL",
            "> VERDICT: PASS": "PASS",
            "\n\n  VERDICT: PASS  \nrest": "PASS",
            "VERDICT:PASS": "PASS",
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(review.parse_verdict(text), expected)

    def test_anything_else_is_unknown(self) -> None:
        for text in ("", "   \n", "Looks fine to me", "The VERDICT: PASS", "VERDICT: PASSED", "VERDICT: MAYBE", "PASS"):
            with self.subTest(text):
                self.assertEqual(review.parse_verdict(text), "unknown")

    def test_the_recorded_subagent_answer_is_unknown(self) -> None:
        """The B1 recording is a plain answer, not a verifier answer."""
        self.assertEqual(review.parse_verdict(load_payload("PostToolUse.runSubagent.json")["tool_response"]), "unknown")


class ReviewTests(HarnessTestCase):
    """The review checks with the verifier switched on by the policy default."""

    def setUp(self) -> None:
        super().setUp()
        self.verifier_default(True)

    def prompt(self, sid: str, text: str = "[L2] change a file") -> dict:
        return self.hook(payload("UserPromptSubmit", sid, prompt=text))

    def edit(self, sid: str, tool: str = "replace_string_in_file") -> None:
        self.hook(pre_tool(sid, tool, EDIT))
        self.hook(post_tool(sid, tool, EDIT))

    def read(self, sid: str, times: int = 1) -> None:
        for _ in range(times):
            self.hook(pre_tool(sid, "read_file", {"filePath": "/w/a.txt"}))
            self.hook(post_tool(sid, "read_file", {"filePath": "/w/a.txt"}))

    def verify(self, sid: str, answer: str = "VERDICT: PASS\n- ok", agent: str = "verifier") -> dict:
        tool_input = {**VERIFIER, "agentName": agent}
        output = self.hook(pre_tool(sid, "runSubagent", tool_input))
        if not output:
            self.hook(post_tool(sid, "runSubagent", tool_input, answer))
        return output

    def stop(self, sid: str, active: bool = False) -> dict:
        return self.hook(payload("Stop", sid, stop_hook_active=active))

    def blocked(self, output: dict) -> bool:
        body = output.get("hookSpecificOutput", {})
        return body.get("decision") == "block"

    def reason(self, output: dict) -> str:
        return output["hookSpecificOutput"]["reason"]

    def state(self, sid: str) -> dict:
        return self.task_level_state(sid)

    # --- recording ----------------------------------------------------------------------------

    def test_edits_are_noted_after_they_happen(self) -> None:
        self.prompt("rec")
        self.hook(pre_tool("rec", "replace_string_in_file", EDIT))
        self.assertEqual(self.state("rec")["prompt"]["edits"], 0)  # not yet: PreToolUse may still be denied
        self.hook(post_tool("rec", "replace_string_in_file", EDIT))
        self.edit("rec", "create_file")
        self.read("rec")
        prompt = self.state("rec")["prompt"]
        self.assertEqual(prompt["edits"], 2)
        self.assertGreater(prompt["last_edit_seq"], 0)

    def test_a_new_prompt_forgets_edits_and_reviews(self) -> None:
        self.prompt("forget")
        self.edit("forget")
        self.verify("forget")
        self.prompt("forget", "next prompt")
        state = self.state("forget")
        self.assertEqual((state["prompt"]["edits"], state["reviews"]), (0, []))

    def test_only_the_verifier_is_recorded_as_a_review(self) -> None:
        self.prompt("who")
        self.hook(pre_tool("who", "runSubagent", {**VERIFIER, "agentName": "builder"}))  # denied at L2
        self.hook(post_tool("who", "runSubagent", {**VERIFIER, "agentName": "builder"}, "VERDICT: PASS"))
        self.assertEqual(self.state("who")["reviews"], [])
        self.verify("who", "VERDICT: FAIL\n- a test fails")
        self.assertEqual([r["verdict"] for r in self.state("who")["reviews"]], ["FAIL"])

    def test_the_agent_name_is_matched_without_case(self) -> None:
        self.prompt("case")
        self.verify("case", agent="Verifier")
        self.assertEqual(len(self.state("case")["reviews"]), 1)

    # --- the Stop check, one test per branch (M2-5) --------------------------------------------

    def test_l2_a_edit_then_verifier_pass_stops_normally(self) -> None:
        self.prompt("a")
        self.edit("a")
        self.verify("a")
        self.assertEqual(self.stop("a"), {})

    def test_l2_b_edit_without_a_review_is_blocked_once_then_a_review_lets_it_stop(self) -> None:
        self.prompt("b")
        self.edit("b")
        first = self.stop("b")
        self.assertTrue(self.blocked(first))
        self.assertEqual(first["hookSpecificOutput"]["hookEventName"], "Stop")
        reason = self.reason(first)
        self.assertIn("verifier", reason)
        self.assertIn("改了文件", reason)
        self.assertIn("[no-verify]", reason)
        self.verify("b")
        self.assertEqual(self.stop("b", active=True), {})  # the second Stop of the chain carries stop_hook_active

    def test_the_stop_hook_active_flag_always_lets_it_stop(self) -> None:
        self.prompt("active")
        self.edit("active")
        self.assertEqual(self.stop("active", active=True), {})

    def test_l2_c_fail_without_a_later_edit_is_not_blocked(self) -> None:
        self.prompt("c")
        self.edit("c")
        self.verify("c", "VERDICT: FAIL\n- bug")
        self.assertEqual(self.stop("c"), {})  # the agent hands the problem to the user

    def test_fail_then_a_fix_needs_a_new_review(self) -> None:
        self.prompt("fix")
        self.edit("fix")
        self.verify("fix", "VERDICT: FAIL\n- bug")
        self.edit("fix")
        blocked = self.stop("fix")
        self.assertTrue(self.blocked(blocked))
        self.assertIn("上一次复核之后你又改了文件", self.reason(blocked))
        self.verify("fix", "VERDICT: PASS")
        self.assertEqual(self.stop("fix"), {})

    def test_an_edit_after_a_pass_needs_a_new_review(self) -> None:
        self.prompt("late")
        self.edit("late")
        self.verify("late")
        self.edit("late")
        self.assertTrue(self.blocked(self.stop("late")))

    def test_l2_d_an_exhausted_verifier_lets_it_stop(self) -> None:
        self.prompt("used")
        self.edit("used")
        self.verify("used", "VERDICT: FAIL")
        self.edit("used")
        self.verify("used", "VERDICT: FAIL")
        self.edit("used")  # a third round would need a third call, but only two are allowed
        self.assertEqual(self.stop("used"), {})
        self.assertEqual(self.state("used")["counters"]["subagents_created"], 2)

    def test_l2_e_no_verify_skips_the_check_for_one_prompt(self) -> None:
        self.prompt("skip", "[L2] [no-verify] quick change")
        self.edit("skip")
        self.assertEqual(self.stop("skip"), {})
        self.prompt("skip", "another change")
        self.edit("skip")
        self.assertTrue(self.blocked(self.stop("skip")))

    def test_l2_f_a_light_question_needs_no_review(self) -> None:
        self.prompt("light", "[L2] explain a.txt")
        self.read("light", 3)
        self.assertEqual(self.stop("light"), {})

    def test_many_tool_calls_need_a_review_even_without_edits(self) -> None:
        self.prompt("heavy", "[L2] investigate")
        self.read("heavy", 10)
        blocked = self.stop("heavy")
        self.assertTrue(self.blocked(blocked))
        self.assertIn("工具调用已达 10 次", self.reason(blocked))
        self.assertNotIn("改了文件", self.reason(blocked))

    def test_one_tool_call_fewer_than_the_threshold_needs_no_review(self) -> None:
        self.prompt("almost", "[L2] investigate")
        self.read("almost", 9)
        self.assertEqual(self.stop("almost"), {})

    def test_a_null_threshold_means_only_edits_count(self) -> None:
        path = self.root / ".harness" / "policies" / "task-levels.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["levels"]["2"]["verification"]["require_when"]["min_tool_calls"] = None
        path.write_text(json.dumps(data), encoding="utf-8")
        self.prompt("null", "[L2] investigate")
        self.read("null", 30)
        self.assertEqual(self.stop("null"), {})
        self.edit("null")
        self.assertTrue(self.blocked(self.stop("null")))

    def test_an_unreadable_verdict_does_not_block_again(self) -> None:
        self.prompt("unknown")
        self.edit("unknown")
        self.verify("unknown", "Looks fine to me")
        self.assertEqual([r["verdict"] for r in self.state("unknown")["reviews"]], ["unknown"])
        self.assertEqual(self.stop("unknown"), {})

    def test_l1_never_asks_for_a_review(self) -> None:
        self.prompt("l1", "change a file")
        self.edit("l1")
        self.read("l1", 20)
        self.assertEqual(self.stop("l1"), {})

    def test_a_running_l3_request_is_not_checked_here(self) -> None:
        self.prompt("l3")
        self.edit("l3")
        path = self.state_file("l3")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["active_request"] = "req-1"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.stop("l3"), {})

    def test_a_shell_edit_is_not_seen(self) -> None:
        """Known limit: a terminal command that writes a file is not an edit tool call."""
        self.prompt("shell")
        self.hook(pre_tool("shell", "run_in_terminal", {"command": "echo hi > a.txt", "mode": "sync"}))
        self.hook(post_tool("shell", "run_in_terminal", {"command": "echo hi > a.txt", "mode": "sync"}))
        self.assertEqual(self.stop("shell"), {})

    def test_the_rules_for_the_prompt_mention_the_review(self) -> None:
        context = self.prompt("rules")["additionalContext"]
        self.assertIn("复核：本条提示改了文件或工具调用达到 10 次时", context)
        self.assertIn("调用 verifier 复核一次", context)
        self.assertIn("[no-verify]", context)
        level1 = self.prompt("rules", "[L1] small")["additionalContext"]
        self.assertNotIn("复核", level1)

    def test_a_denied_edit_is_not_an_edit(self) -> None:
        """PostToolUse never fires for a denied call, so nothing is noted. The check follows what happened."""
        self.prompt("denied")
        self.hook(pre_tool("denied", "replace_string_in_file", EDIT))  # PostToolUse does not follow
        self.assertEqual(self.stop("denied"), {})

    def test_the_review_check_fails_open_on_a_broken_state(self) -> None:
        self.prompt("broken")
        self.edit("broken")
        path = self.state_file("broken")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["modules"]["task_level"]["reviews"] = "oops"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.stop("broken"), {})
        self.assertTrue(self.log_lines("hook-errors.jsonl"))


if __name__ == "__main__":
    unittest.main()


class VerifierSwitchTests(HarnessTestCase):
    """M2-8: the verifier is off by default. `[verify]` turns it on for one prompt, `[no-verify]` turns it off."""

    def prompt(self, sid: str, text: str) -> dict:
        return self.hook(payload("UserPromptSubmit", sid, prompt=text))

    def edit(self, sid: str) -> None:
        self.hook(pre_tool(sid, "replace_string_in_file", EDIT))
        self.hook(post_tool(sid, "replace_string_in_file", EDIT))

    def call(self, sid: str, agent: str = "verifier") -> dict:
        return self.hook(pre_tool(sid, "runSubagent", {**VERIFIER, "agentName": agent}))

    def stop(self, sid: str) -> dict:
        return self.hook(payload("Stop", sid, stop_hook_active=False))

    def decision(self, output: dict) -> str:
        return output.get("hookSpecificOutput", {}).get("permissionDecision", "")

    def test_the_shipped_default_is_off(self) -> None:
        policy = json.loads((self.root / ".harness" / "policies" / "task-levels.json").read_text(encoding="utf-8"))
        self.assertIs(policy["levels"]["2"]["verification"]["enabled"], False)

    def test_off_the_verifier_call_is_denied_with_the_way_to_turn_it_on(self) -> None:
        self.prompt("off", "[L2] change a file")
        denied = self.call("off")
        self.assertEqual(self.decision(denied), "deny")
        reason = denied["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("没有开启 verifier 复核", reason)
        self.assertIn("[verify]", reason)
        self.assertEqual(self.task_level_state("off")["counters"]["subagents_created"], 0)

    def test_off_a_generic_subagent_gets_the_same_answer(self) -> None:
        self.prompt("off-generic", "[L2] change a file")
        denied = self.hook(pre_tool("off-generic", "runSubagent", {"prompt": "x", "description": "x"}))
        self.assertEqual(self.decision(denied), "deny")
        self.assertIn("[verify]", denied["hookSpecificOutput"]["permissionDecisionReason"])

    def test_off_stop_never_asks_for_a_review(self) -> None:
        self.prompt("off-stop", "[L2] change a file")
        self.edit("off-stop")
        for _ in range(10):
            self.hook(pre_tool("off-stop", "read_file", {"filePath": "/w/a.txt"}))
        self.assertEqual(self.stop("off-stop"), {})

    def test_off_the_prompt_rules_say_so_and_do_not_ask_for_a_review(self) -> None:
        context = self.prompt("off-rules", "[L2] go")["additionalContext"]
        self.assertIn("没有开启 verifier 复核", context)
        self.assertNotIn("调用 verifier 复核一次", context)

    def test_the_enable_marker_turns_it_on_for_that_prompt_only(self) -> None:
        self.prompt("on", "[L2] [verify] change a file")
        self.edit("on")
        self.assertEqual(self.call("on"), {})  # allowed
        self.assertEqual(self.task_level_state("on")["counters"]["subagents_created"], 1)
        self.hook(post_tool("on", "runSubagent", {**VERIFIER}, "VERDICT: PASS"))
        self.assertEqual(self.stop("on"), {})
        self.prompt("on", "next change")  # the marker does not carry over
        self.assertEqual(self.decision(self.call("on")), "deny")

    def test_the_enable_marker_makes_stop_ask_for_a_review(self) -> None:
        self.prompt("ask", "[L2] [verify] change a file")
        self.edit("ask")
        blocked = self.stop("ask")
        self.assertEqual(blocked["hookSpecificOutput"]["decision"], "block")
        self.assertIn("改了文件", blocked["hookSpecificOutput"]["reason"])

    def test_no_verify_wins_when_both_markers_are_written(self) -> None:
        self.prompt("both", "[L2] [verify] [no-verify] change a file")
        self.edit("both")
        self.assertEqual(self.stop("both"), {})
        self.assertEqual(self.decision(self.call("both")), "deny")

    def test_a_default_on_policy_can_still_be_turned_off_per_prompt(self) -> None:
        self.verifier_default(True)
        self.prompt("default-on", "[L2] change a file")
        self.edit("default-on")
        self.assertEqual(self.stop("default-on")["hookSpecificOutput"]["decision"], "block")
        self.prompt("default-on", "[no-verify] another change")
        self.edit("default-on")
        self.assertEqual(self.stop("default-on"), {})

    def test_an_agent_cannot_turn_it_on_by_writing_the_marker_in_a_call_message(self) -> None:
        self.hook(payload("UserPromptSubmit", "child", prompt="[L2] change a file"))
        self.hook(payload("SubagentStart", "child", agent_id="a1", agent_type="verifier"))
        self.assertEqual(self.hook(payload("UserPromptSubmit", "child", prompt="[verify] model text")), {})
        self.assertEqual(self.task_level_state("child")["prompt"]["verify"], "")

    def test_l1_has_no_verifier_either_way(self) -> None:
        self.prompt("l1", "[L1] [verify] small change")
        self.edit("l1")
        self.assertEqual(self.stop("l1"), {})
        self.assertEqual(self.decision(self.call("l1")), "deny")
