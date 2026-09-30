"""adapters/: real VS Code payloads -> HookEvent, and Decision -> runtime output."""

from __future__ import annotations

import json
import unittest

from support import FIXTURES, iter_session, load_payload

import adapters
from adapters import common, copilot_cli, copilot_vscode
from core.events import EVENT_NAMES, Decision


class VsCodeParseTests(unittest.TestCase):
    def test_every_recorded_payload_parses_with_the_right_event_and_session(self) -> None:
        files = sorted((FIXTURES / "payloads").glob("*.json"))
        self.assertGreaterEqual(len(files), 24)
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(path.name):
                self.assertIs(adapters.detect(data), copilot_vscode)
                event = copilot_vscode.parse(data)
                self.assertEqual(event.event, data["hook_event_name"])
                self.assertEqual(event.session_id, data["session_id"])
                self.assertEqual(event.surface, "vscode")
                self.assertFalse(event.from_subagent)

    def test_every_recorded_tool_has_a_known_kind(self) -> None:
        kinds = {}
        for session in sorted((FIXTURES / "sessions").glob("*.jsonl")):
            for data in iter_session(session.name):
                if data["hook_event_name"] == "PreToolUse":
                    kinds[data["tool_name"]] = copilot_vscode.parse(data).tool_kind
        self.assertEqual(
            kinds,
            {
                "read_file": "read",
                "list_dir": "read",
                "grep_search": "search",
                "file_search": "search",
                "semantic_search": "search",
                "create_file": "create",
                "replace_string_in_file": "edit",
                "run_in_terminal": "terminal",
                "runSubagent": "subagent",
            },
        )

    def test_all_eight_event_names_are_known(self) -> None:
        self.assertEqual(
            set(EVENT_NAMES),
            {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PreCompact", "SubagentStart", "SubagentStop", "Stop"},
        )

    def test_session_start_and_prompt_fields(self) -> None:
        event = copilot_vscode.parse(load_payload("UserPromptSubmit.json"))
        self.assertTrue(event.prompt.startswith("依次做四件事"))
        self.assertEqual(event.cwd, "/Users/user/Developer/DE-agentic-harness")
        self.assertEqual(event.tool_kind, "")

    def test_run_subagent_fields(self) -> None:
        event = copilot_vscode.parse(load_payload("PreToolUse.runSubagent.json"))
        self.assertEqual(event.tool_kind, "subagent")
        self.assertEqual(event.subagent_target, "probe-child")
        self.assertTrue(event.subagent_prompt.startswith("请读取文件"))
        self.assertTrue(event.tool_use_id.startswith("toolu_"))

    def test_run_subagent_response_is_the_final_answer(self) -> None:
        event = copilot_vscode.parse(load_payload("PostToolUse.runSubagent.json"))
        self.assertEqual(event.tool_response, "# 数据工程智能体框架")

    def test_terminal_command_and_search_detection(self) -> None:
        event = copilot_vscode.parse(load_payload("PreToolUse.run_in_terminal.json"))
        self.assertEqual(event.tool_kind, "terminal")
        self.assertEqual(event.command, "git status --short")
        self.assertFalse(event.is_search)
        self.assertTrue(copilot_vscode.parse(load_payload("PreToolUse.grep_search.json")).is_search)
        self.assertTrue(common.is_terminal_search("cd x && grep -r foo ."))
        self.assertTrue(common.is_terminal_search("git   grep foo"))
        self.assertTrue(common.is_terminal_search("find . -name '*.py'"))
        self.assertFalse(common.is_terminal_search("echo grep"))
        self.assertFalse(common.is_terminal_search("git status"))

    def test_file_paths_are_collected(self) -> None:
        event = copilot_vscode.parse(load_payload("PreToolUse.read_file.json"))
        self.assertEqual(len(event.paths), 1)
        self.assertTrue(event.paths[0].endswith(".md") or "/" in event.paths[0])
        listing = copilot_vscode.parse(load_payload("PreToolUse.list_dir.json"))
        self.assertEqual(len(listing.paths), 1)

    def test_subagent_events_carry_agent_fields_and_stop_flag(self) -> None:
        start = copilot_vscode.parse(load_payload("SubagentStart.json"))
        self.assertEqual((start.agent_type, start.agent_id[:6]), ("probe-child", "toolu_"))
        self.assertFalse(copilot_vscode.parse(load_payload("Stop.json")).stop_hook_active)
        self.assertTrue(copilot_vscode.parse(load_payload("Stop.active.json")).stop_hook_active)

    def test_bad_payloads_raise(self) -> None:
        for bad in (
            {"hook_event_name": "Nope", "session_id": "s"},
            {"hook_event_name": "PreToolUse"},
            {"hook_event_name": "PreToolUse", "session_id": ""},
        ):
            with self.assertRaises(ValueError):
                copilot_vscode.parse(bad)
        with self.assertRaises(ValueError):
            adapters.detect({"something": "else"})


class VsCodeRenderTests(unittest.TestCase):
    def render(self, payload_name: str, decision: Decision) -> dict:
        event = copilot_vscode.parse(load_payload(payload_name))
        return copilot_vscode.render(event, decision)

    def test_deny_is_nested_with_the_event_name(self) -> None:
        output = self.render("PreToolUse.runSubagent.json", Decision(permission="deny", reason="not allowed"))
        self.assertEqual(
            output,
            {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "not allowed"}},
        )

    def test_ask_is_nested(self) -> None:
        output = self.render("PreToolUse.run_in_terminal.json", Decision(permission="ask", reason="sure?"))
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_stop_block_is_nested(self) -> None:
        output = self.render("Stop.json", Decision(block=True, reason="run the verifier"))
        self.assertEqual(output, {"hookSpecificOutput": {"hookEventName": "Stop", "decision": "block", "reason": "run the verifier"}})

    def test_context_goes_to_user_prompt_session_start_and_subagent_start(self) -> None:
        for name, event in (("UserPromptSubmit.json", "UserPromptSubmit"), ("SessionStart.json", "SessionStart"), ("SubagentStart.json", "SubagentStart")):
            with self.subTest(name):
                output = self.render(name, Decision(context="rules"))
                self.assertEqual(output, {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "rules"}})

    def test_empty_decision_is_an_empty_object(self) -> None:
        self.assertEqual(self.render("PreToolUse.read_file.json", Decision()), {})
        self.assertEqual(copilot_vscode.render(copilot_vscode.parse(load_payload("Stop.json")), None), {})

    def test_a_permission_on_the_wrong_event_is_dropped(self) -> None:
        self.assertEqual(self.render("UserPromptSubmit.json", Decision(permission="deny", reason="x")), {})


class CliAdapterTests(unittest.TestCase):
    """Copilot CLI is not verified (M6-4). These tests only pin what the adapter does with documented shapes."""

    def test_camel_case_payload_with_string_tool_args(self) -> None:
        data = {
            "sessionId": "cli-1",
            "hookEventName": "PreToolUse",
            "toolName": "bash",
            "toolArgs": json.dumps({"command": "grep -r x ."}),
            "cwd": "/w",
        }
        self.assertIs(adapters.detect(data), copilot_cli)
        event = copilot_cli.parse(data)
        self.assertEqual((event.surface, event.event, event.session_id), ("cli", "PreToolUse", "cli-1"))
        self.assertEqual(event.tool_kind, "terminal")
        self.assertTrue(event.is_search)

    def test_old_style_event_names_are_translated(self) -> None:
        event = copilot_cli.parse({"sessionId": "c", "event": "userPromptSubmitted", "prompt": "hi"})
        self.assertEqual(event.event, "UserPromptSubmit")

    def test_output_is_top_level(self) -> None:
        data = {"sessionId": "c", "hookEventName": "PreToolUse", "toolName": "task", "toolArgs": {"prompt": "x"}}
        event = copilot_cli.parse(data)
        self.assertEqual(event.tool_kind, "subagent")
        self.assertEqual(
            copilot_cli.render(event, Decision(permission="deny", reason="no")),
            {"permissionDecision": "deny", "permissionDecisionReason": "no"},
        )

    def test_vscode_shape_wins_detection(self) -> None:
        self.assertIs(adapters.detect(load_payload("PreToolUse.read_file.json")), copilot_vscode)


class ToolKindsFileTests(unittest.TestCase):
    def test_kinds_are_from_the_known_set_and_vscode_is_marked_verified(self) -> None:
        data = common.tool_kinds()
        for surface, body in data["surfaces"].items():
            for tool, kind in body["tools"].items():
                self.assertIn(kind, {"read", "edit", "create", "terminal", "search", "subagent", "mcp"}, f"{surface}:{tool}")
        self.assertTrue(data["surfaces"]["vscode"]["verified"])
        self.assertFalse(data["surfaces"]["cli"]["verified"])

    def test_unknown_tools_are_kind_other(self) -> None:
        event = copilot_vscode.parse({"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "brand_new_tool", "tool_input": {}})
        self.assertEqual(event.tool_kind, "other")


if __name__ == "__main__":
    unittest.main()
