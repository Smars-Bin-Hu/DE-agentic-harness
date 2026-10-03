"""The L3 end checks (B9-B, M5-1): Stop, SubagentStop and `request wait`. They ask for the paperwork once, never argue."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict

from support import payload

from core.state import update_state
from test_request import SESSION, RequestCase


def blocked(output: Dict[str, Any]) -> bool:
    return output.get("hookSpecificOutput", {}).get("decision") == "block" or output.get("decision") == "block"


def reason_of(output: Dict[str, Any]) -> str:
    return output.get("hookSpecificOutput", {}).get("reason") or output.get("reason", "")


class VerifyCase(RequestCase):
    def stop(self, active: bool = False, session: str = SESSION) -> Dict[str, Any]:
        return self.hook(payload("Stop", session, stop_hook_active=active))

    def sub_stop(self, role: str = "builder", session: str = SESSION) -> Dict[str, Any]:
        return self.hook(payload("SubagentStop", session, agent_id="a1", agent_type=role, stop_hook_active=False))

    def user_prompt(self, text: str = "ok") -> Dict[str, Any]:
        return self.hook(payload("UserPromptSubmit", SESSION, prompt=text))

    def conclude(self, request_id: str, status: str = "abandoned") -> None:
        self.run_cli("request", "set-status", "--request", request_id, "--status", status, "--reason", "test")

    def wait(self, request_id: str, reason: str = "waiting for the person") -> Dict[str, Any]:
        return self.run_cli("request", "wait", "--request", request_id, "--reason", reason)

    def set_verify(self, **changes: Any) -> None:
        path = self.root / ".harness" / "policies" / "orchestration.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("verify", {"main_stop": True, "subagent_stop": "block"}).update(changes)
        path.write_text(json.dumps(data), encoding="utf-8")

    def dispatched_builder(self, request_id: str, number: int = 1) -> None:
        self.attempt(request_id)
        self.fill_assignment(request_id, number, "builder")
        self.dispatch(request_id, "builder")


class MainStopTests(VerifyCase):
    def test_no_request_no_block(self) -> None:
        self.assertFalse(blocked(self.stop()))

    def test_an_open_request_blocks_once_and_says_both_ways_out(self) -> None:
        request_id = self.new_request()
        first = self.stop()
        self.assertTrue(blocked(first))
        reason = reason_of(first)
        self.assertIn(request_id, reason)
        self.assertIn("request set-status", reason)
        self.assertIn("check --request", reason)
        self.assertIn("request wait", reason)

    def test_the_second_stop_of_a_block_goes_through(self) -> None:
        self.new_request()
        self.assertTrue(blocked(self.stop()))
        self.assertFalse(blocked(self.stop(active=True)))

    def test_a_concluded_request_does_not_block(self) -> None:
        request_id = self.new_request()
        self.conclude(request_id, "abandoned")
        self.assertFalse(blocked(self.stop()))

    def test_a_request_marked_as_waiting_does_not_block(self) -> None:
        request_id = self.new_request()
        self.wait(request_id)
        self.assertFalse(blocked(self.stop()))

    def test_the_block_is_in_the_call_log_with_the_module_and_the_kind(self) -> None:
        self.new_request()
        self.stop()
        row = self.session_log(SESSION)[-1]
        self.assertEqual((row["event"], row["decision"], row["judge"], row["by"], row["kind"]), ("Stop", "block", "rule", ["request"], "request_not_concluded"))

    def test_the_policy_can_turn_the_main_stop_check_off(self) -> None:
        self.new_request()
        self.set_verify(main_stop=False)
        self.assertFalse(blocked(self.stop()))

    def test_a_subagent_session_is_not_checked_by_the_main_stop(self) -> None:
        self.new_request()
        update_state(self.root, "vscode", SESSION, lambda state: state.update(parent_session_id="parent"))
        self.assertFalse(blocked(self.stop()))

    def test_a_broken_request_file_does_not_block_anything(self) -> None:
        request_id = self.new_request()
        (self.rd(request_id) / "request.json").write_text("{broken", encoding="utf-8")
        self.assertFalse(blocked(self.stop()))
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])


class WaitTests(VerifyCase):
    def test_wait_marks_the_request_and_list_and_show_say_so(self) -> None:
        request_id = self.new_request()
        result = self.wait(request_id, "waiting for approval")
        self.assertEqual(result["waiting_for"], "waiting for approval")
        self.assertEqual(self.request(request_id)["waiting"]["reason"], "waiting for approval")
        listed = self.run_cli("request", "list")["requests"][0]
        self.assertEqual(listed["waiting_for"], "waiting for approval")
        self.assertEqual(self.request(request_id)["status"], "open")

    def test_a_reason_is_required(self) -> None:
        request_id = self.new_request()
        self.assertIn("--reason", self.refused("request", "wait", "--request", request_id, "--reason", "  "))

    def test_a_concluded_request_cannot_wait(self) -> None:
        request_id = self.new_request()
        self.conclude(request_id)
        self.assertIn("已经结束", self.refused("request", "wait", "--request", request_id, "--reason", "x"))

    def test_the_next_user_prompt_clears_the_mark(self) -> None:
        request_id = self.new_request()
        self.wait(request_id)
        self.user_prompt("I approve")
        self.assertNotIn("waiting", self.request(request_id))
        self.assertTrue(blocked(self.stop()))  # open and no longer waiting

    def test_a_subagent_call_message_does_not_clear_the_mark(self) -> None:
        request_id = self.new_request()
        self.wait(request_id)
        self.hook(payload("SubagentStart", SESSION, agent_id="a1", agent_type="builder"))
        self.user_prompt("the message the orchestrator wrote for the builder")
        self.assertIn("waiting", self.request(request_id))
        self.hook(payload("SubagentStop", SESSION, agent_id="a1", agent_type="builder", stop_hook_active=False))
        self.user_prompt("a real prompt")
        self.assertNotIn("waiting", self.request(request_id))

    def test_conclusion_clears_the_mark(self) -> None:
        request_id = self.new_request()
        self.wait(request_id)
        self.conclude(request_id)
        self.assertNotIn("waiting", self.request(request_id))

    def test_clearing_is_in_the_call_log(self) -> None:
        request_id = self.new_request()
        self.wait(request_id)
        self.user_prompt("go on")
        self.assertEqual(self.session_log(SESSION)[-1]["kind"], "wait_cleared")

    def test_the_report_says_who_is_waited_for(self) -> None:
        request_id = self.new_request()
        self.wait(request_id, "waiting for approval")
        self.run_cli("report", "--request", request_id)
        text = (self.root / ".workspace" / "reports" / f"{request_id}.md").read_text(encoding="utf-8")
        self.assertIn("在等人：waiting for approval", text)


class SubagentStopTests(VerifyCase):
    def test_a_builder_that_ends_without_a_handoff_is_blocked_once_with_the_command(self) -> None:
        request_id = self.new_request()
        self.dispatched_builder(request_id)
        first = self.sub_stop()
        self.assertTrue(blocked(first))
        reason = reason_of(first)
        self.assertIn("handoff submit", reason)
        self.assertIn(f"--request {request_id}", reason)
        self.assertIn("--role builder", reason)
        self.assertIn("第 1 轮", reason)
        self.assertIn("blocked", reason)
        self.assertFalse(blocked(self.sub_stop()))  # asked once

    def test_a_handoff_lets_it_end(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.assertFalse(blocked(self.sub_stop()))

    def test_a_blocked_handoff_is_a_handoff(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1, "blocked")
        self.assertFalse(blocked(self.sub_stop()))

    def test_a_reviewer_is_checked_the_same_way(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.fill_assignment(request_id, 1, "reviewer")
        self.dispatch(request_id, "reviewer")
        output = self.sub_stop("reviewer")
        self.assertTrue(blocked(output))
        self.assertIn("--role reviewer", reason_of(output))

    def test_a_role_that_was_not_dispatched_this_attempt_is_left_alone(self) -> None:
        request_id = self.new_request()
        self.dispatched_builder(request_id)
        self.assertFalse(blocked(self.sub_stop("reviewer")))

    def test_the_next_attempt_is_asked_again(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.reviewer_round(request_id, 1, "failed")
        self.attempt(request_id)
        self.fill_assignment(request_id, 2, "builder")
        self.dispatch(request_id, "builder")
        output = self.sub_stop()
        self.assertTrue(blocked(output))
        self.assertIn("第 2 轮", reason_of(output))

    def test_a_recorded_handoff_whose_file_is_gone_does_not_count(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        path = self.rd(request_id) / "handoffs" / "builder" / "attempt-001" / "handoff.json"
        path.chmod(0o644)
        path.unlink()
        self.assertTrue(blocked(self.sub_stop()))

    def test_other_agents_and_no_request_are_left_alone(self) -> None:
        self.assertFalse(blocked(self.sub_stop()))  # no request
        request_id = self.new_request()
        self.dispatched_builder(request_id)
        self.assertFalse(blocked(self.sub_stop("verifier")))
        self.assertFalse(blocked(self.sub_stop("search-subagent")))

    def test_a_concluded_request_is_left_alone(self) -> None:
        request_id = self.new_request()
        self.dispatched_builder(request_id)
        self.conclude(request_id)
        self.assertFalse(blocked(self.sub_stop()))

    def test_log_mode_records_the_gap_and_does_not_block(self) -> None:
        request_id = self.new_request()
        self.dispatched_builder(request_id)
        self.set_verify(subagent_stop="log")
        self.assertFalse(blocked(self.sub_stop()))
        row = self.session_log(SESSION)[-1]
        self.assertEqual((row["event"], row["decision"], row["kind"]), ("SubagentStop", "none", "missing_handoff"))

    def test_off_mode_does_nothing(self) -> None:
        request_id = self.new_request()
        self.dispatched_builder(request_id)
        self.set_verify(subagent_stop="off")
        self.assertFalse(blocked(self.sub_stop()))
        self.assertNotIn("kind", self.session_log(SESSION)[-1])

    def test_the_block_is_in_the_call_log(self) -> None:
        request_id = self.new_request()
        self.dispatched_builder(request_id)
        self.sub_stop()
        row = self.session_log(SESSION)[-1]
        self.assertEqual((row["decision"], row["judge"], row["by"], row["kind"]), ("block", "rule", ["request"], "missing_handoff"))

    def test_the_sdk_engine_reports_the_stop_on_the_parent_and_gets_a_top_level_block(self) -> None:
        request_id = self.new_request()
        self.dispatched_builder(request_id)
        output = self.hook({
            "hook_event_name": "SubagentStop", "session_id": SESSION, "timestamp": "2026-10-02T00:00:00.000Z", "cwd": "/x",
            "agent_id": "child-session", "agent_type": "builder", "agent_name": "builder", "last_assistant_message": "done", "stop_reason": "end_turn",
        })
        self.assertEqual(output["decision"], "block")
        self.assertIn("handoff submit", output["reason"])


class PolicyTests(VerifyCase):
    def test_the_shipped_policy_has_both_checks_on(self) -> None:
        policy = json.loads((self.root / ".harness" / "policies" / "orchestration.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["verify"], {"main_stop": True, "subagent_stop": "block"})

    def test_a_policy_without_verify_uses_the_defaults(self) -> None:
        path = self.root / ".harness" / "policies" / "orchestration.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["verify"]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.new_request()
        self.assertTrue(blocked(self.stop()))

    def test_a_bad_value_is_an_error_in_doctor_and_the_hook_fails_open(self) -> None:
        request_id = self.new_request()
        self.dispatched_builder(request_id)
        self.set_verify(subagent_stop="sometimes")
        self.assertFalse(blocked(self.sub_stop()))  # no block, no crash
        self.assertFalse(blocked(self.stop()))
        self.assertTrue(any("module:request" in item["where"] for item in self.log_lines("hook-errors.jsonl")))


if __name__ == "__main__":
    unittest.main()
