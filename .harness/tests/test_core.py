"""core/: schema, config merge, decision merge, state lock, subagent tracking."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the engine on sys.path)
from core import config, schema, state
from core.events import Decision, HookEvent, merge


class SchemaTests(unittest.TestCase):
    SCHEMA = {
        "type": "object",
        "required": ["name", "kind"],
        "properties": {
            "name": {"type": "string"},
            "kind": {"type": "string", "enum": ["a", "b"]},
            "count": {"type": "integer", "minimum": 0},
            "tags": {"type": "array", "items": {"type": "string"}},
            "maybe": {"type": ["string", "null"]},
        },
    }

    def test_valid_value_has_no_errors(self) -> None:
        self.assertEqual(schema.validate({"name": "x", "kind": "a", "count": 0, "tags": ["t"], "maybe": None}, self.SCHEMA), [])

    def test_reports_type_required_enum_minimum_and_items(self) -> None:
        errors = schema.validate({"kind": "z", "count": -1, "tags": [1]}, self.SCHEMA)
        text = " | ".join(errors)
        self.assertIn("missing required key 'name'", text)
        self.assertIn("'z' is not one of", text)
        self.assertIn("below 0", text)
        self.assertIn("$.tags[0]", text)

    def test_bool_is_not_an_integer(self) -> None:
        self.assertTrue(schema.validate({"name": "x", "kind": "a", "count": True}, self.SCHEMA))

    def test_check_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            schema.check([], self.SCHEMA, "thing")


class ConfigTests(unittest.TestCase):
    def test_deep_merge_replaces_leaves_and_keeps_the_rest(self) -> None:
        base = {"a": {"x": 1, "y": 2}, "b": [1, 2], "c": 3}
        override = {"a": {"y": 9}, "b": [7], "d": 4}
        self.assertEqual(config.deep_merge(base, override), {"a": {"x": 1, "y": 9}, "b": [7], "c": 3, "d": 4})
        self.assertEqual(base["a"]["y"], 2)  # the base is not changed

    def test_a_plus_key_appends_to_the_default_array(self) -> None:
        base = {"a": {"rules": [1, 2]}, "b": [1]}
        merged = config.deep_merge(base, {"a": {"rules+": [3]}, "b+": [2, 3]})
        self.assertEqual(merged, {"a": {"rules": [1, 2, 3]}, "b": [1, 2, 3]})
        self.assertEqual(base["b"], [1])

    def test_a_plus_key_with_no_default_array_starts_one(self) -> None:
        self.assertEqual(config.deep_merge({"a": 1}, {"new+": [1]}), {"a": 1, "new": [1]})
        self.assertEqual(config.deep_merge({"a": 1}, {"sub": {"new+": [1]}}), {"a": 1, "sub": {"new": [1]}})

    def test_replace_and_append_of_the_same_key_replace_first(self) -> None:
        self.assertEqual(config.deep_merge({"b": [1, 2]}, {"b+": [9], "b": [5]}), {"b": [5, 9]})

    def test_a_plus_key_on_something_that_is_not_an_array_is_an_error(self) -> None:
        for base, override in (({"a": 1}, {"a+": [1]}), ({"a": [1]}, {"a+": 2}), ({"a": {"x": 1}}, {"a+": [1]})):
            with self.assertRaises(config.OverrideError):
                config.deep_merge(base, override)

    def test_changes_say_how_each_value_came_from_the_override(self) -> None:
        base = {"a": {"x": 1, "rules": [1, 2]}, "b": [1], "c": 3}
        override = {"a": {"x": 5, "rules+": [3]}, "b": [7, 8], "d": 1}
        self.assertEqual(
            config.changes(base, override),
            [("a.x", "replaced", 0), ("a.rules", "appended", 1), ("b", "replaced", 1), ("d", "added", 0)],
        )

    def test_load_policy_applies_the_override_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            policies = Path(directory) / ".harness" / "policies"
            policies.mkdir(parents=True)
            (policies / "demo.json").write_text(json.dumps({"n": 1, "m": {"a": 1, "b": 2}}), encoding="utf-8")
            self.assertEqual(config.load_policy(Path(directory), "demo"), {"n": 1, "m": {"a": 1, "b": 2}})
            (policies / "demo.override.json").write_text(json.dumps({"m": {"b": 5}}), encoding="utf-8")
            self.assertEqual(config.load_policy(Path(directory), "demo"), {"n": 1, "m": {"a": 1, "b": 5}})

    def test_a_bom_at_the_start_of_a_json_file_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bom.json"
            path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"ok": True}).encode())
            self.assertEqual(config.read_json(path), {"ok": True})


class DecisionTests(unittest.TestCase):
    def test_deny_beats_ask_beats_allow(self) -> None:
        merged = merge([Decision(permission="allow"), Decision(permission="deny", reason="no"), Decision(permission="ask", reason="hm")])
        self.assertEqual(merged.permission, "deny")
        self.assertEqual(merged.reason, "no")
        self.assertEqual(merge([Decision(permission="allow"), Decision(permission="ask", reason="hm")]).permission, "ask")

    def test_contexts_join_in_order_and_none_is_ignored(self) -> None:
        merged = merge([Decision(context="one"), None, Decision(context="two")])
        self.assertEqual(merged.context, "one\n\ntwo")

    def test_one_block_is_enough(self) -> None:
        merged = merge([Decision(), Decision(block=True, reason="verify first")])
        self.assertTrue(merged.block)
        self.assertEqual(merged.reason, "verify first")

    def test_nothing_in_nothing_out(self) -> None:
        self.assertTrue(merge([]).is_empty())
        self.assertTrue(merge([None, Decision()]).is_empty())


class StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def event(self, name: str, **fields: object) -> HookEvent:
        return HookEvent(surface="vscode", event=name, session_id="s", **fields)

    def test_effective_level_is_three_while_a_request_is_active(self) -> None:
        current = state.new_state("vscode", "s")
        self.assertEqual(state.effective_level(current), 1)
        current["level"] = 2
        self.assertEqual(state.effective_level(current), 2)
        current["active_request"] = "20260930-1200-demo-ab12"
        self.assertEqual(state.effective_level(current), 3)

    def test_state_round_trip_and_validation(self) -> None:
        state.update_state(self.root, "vscode", "s", lambda data: data.update(level=2))
        path = state.state_path(self.root, "vscode", "s")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["level"], 2)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["level"] = 7
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            state.read_state(path, "vscode", "s")

    def test_state_of_another_session_is_rejected(self) -> None:
        state.update_state(self.root, "vscode", "a.b", lambda data: None)
        path = state.state_path(self.root, "vscode", "a.b")
        with self.assertRaises(ValueError):
            state.read_state(path, "vscode", "other")

    def test_a_failed_block_does_not_write_the_state(self) -> None:
        state.update_state(self.root, "vscode", "s", lambda data: data.update(level=2))

        def broken(data: dict) -> None:
            data["level"] = 1
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            state.update_state(self.root, "vscode", "s", broken)
        path = state.state_path(self.root, "vscode", "s")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["level"], 2)
        self.assertFalse(path.with_suffix(".json.lock").exists())  # the lock is released

    def test_unsafe_session_ids_are_made_safe(self) -> None:
        self.assertEqual(state.safe_session_id("a/b\\c"), "a_b_c")
        self.assertTrue(state.safe_session_id("..").startswith("session-"))
        with self.assertRaises(ValueError):
            state.safe_session_id("")

    # --- I-9: stale lock ----------------------------------------------------------------------

    def test_a_stale_lock_is_cleared_instead_of_blocking_forever(self) -> None:
        path = state.state_path(self.root, "vscode", "s")
        lock = path.with_suffix(".json.lock")
        lock.mkdir(parents=True)
        old = time.time() - 60
        os.utime(lock, (old, old))
        started = time.monotonic()
        state.update_state(self.root, "vscode", "s", lambda data: data.update(level=2))
        self.assertLess(time.monotonic() - started, state.LOCK_STALE_SECONDS)
        self.assertFalse(lock.exists())

    def test_a_fresh_lock_is_respected_until_it_times_out(self) -> None:
        path = state.state_path(self.root, "vscode", "s")
        lock = path.with_suffix(".json.lock")
        lock.mkdir(parents=True)
        original = state.LOCK_TIMEOUT_SECONDS
        state.LOCK_TIMEOUT_SECONDS = 0.2
        self.addCleanup(setattr, state, "LOCK_TIMEOUT_SECONDS", original)
        with self.assertRaises(TimeoutError):
            state.update_state(self.root, "vscode", "s", lambda data: None)
        self.assertTrue(lock.exists())  # not ours, not removed

    # --- subagent tracking --------------------------------------------------------------------

    def test_pending_prompt_is_matched_once_then_the_user_is_the_user_again(self) -> None:
        data = state.new_state("vscode", "s")
        call = self.event("PreToolUse", tool_kind="subagent", subagent_prompt="  read the file  ", subagent_target="verifier")
        state.track_after(data, call, Decision())
        first = self.event("UserPromptSubmit", prompt="read the file")
        state.track_before(data, first)
        self.assertTrue(first.from_subagent)
        second = self.event("UserPromptSubmit", prompt="read the file")
        state.track_before(data, second)
        self.assertFalse(second.from_subagent)

    def test_a_denied_subagent_call_leaves_no_pending_prompt(self) -> None:
        data = state.new_state("vscode", "s")
        call = self.event("PreToolUse", tool_kind="subagent", subagent_prompt="hello")
        state.track_after(data, call, Decision(permission="deny", reason="no"))
        self.assertEqual(data["subagents"]["pending_prompts"], [])

    def test_activity_window_opens_on_start_and_closes_on_stop(self) -> None:
        data = state.new_state("vscode", "s")
        state.track_before(data, self.event("SubagentStart", agent_id="a1", agent_type="x"))
        inside = self.event("UserPromptSubmit", prompt="anything")
        state.track_before(data, inside)
        self.assertTrue(inside.from_subagent)
        state.track_before(data, self.event("SubagentStop", agent_id="a1", agent_type="x"))
        outside = self.event("UserPromptSubmit", prompt="anything")
        state.track_before(data, outside)
        self.assertFalse(outside.from_subagent)

    def test_nested_subagents_keep_the_window_open_until_all_stop(self) -> None:
        data = state.new_state("vscode", "s")
        state.track_before(data, self.event("SubagentStart", agent_id="a1"))
        state.track_before(data, self.event("SubagentStart", agent_id="a2"))
        state.track_before(data, self.event("SubagentStop", agent_id="a2"))
        still = self.event("UserPromptSubmit", prompt="x")
        state.track_before(data, still)
        self.assertTrue(still.from_subagent)

    def test_main_stop_and_session_start_close_a_stuck_window(self) -> None:
        for closing in ("Stop", "SessionStart"):
            data = state.new_state("vscode", "s")
            state.track_before(data, self.event("SubagentStart", agent_id="lost"))
            state.track_before(data, self.event(closing))
            prompt = self.event("UserPromptSubmit", prompt="x")
            state.track_before(data, prompt)
            self.assertFalse(prompt.from_subagent, closing)

    def test_stale_window_and_pending_entries_expire(self) -> None:
        data = state.new_state("vscode", "s")
        data["subagents"]["active"].append({"agent_id": "old", "agent_type": "", "at": time.time() - 3600})
        data["subagents"]["pending_prompts"].append({"prompt": "old", "agent": "", "at": time.time() - 3600})
        prompt = self.event("UserPromptSubmit", prompt="old")
        state.track_before(data, prompt)
        self.assertFalse(prompt.from_subagent)
        self.assertEqual(data["subagents"]["active"], [])

    def test_pending_prompts_are_capped(self) -> None:
        data = state.new_state("vscode", "s")
        for index in range(state.PENDING_PROMPT_MAX + 5):
            state.track_after(data, self.event("PreToolUse", tool_kind="subagent", subagent_prompt=f"p{index}"), Decision())
        self.assertEqual(len(data["subagents"]["pending_prompts"]), state.PENDING_PROMPT_MAX)
        self.assertEqual(data["subagents"]["pending_prompts"][-1]["prompt"], f"p{state.PENDING_PROMPT_MAX + 4}")


if __name__ == "__main__":
    unittest.main()
