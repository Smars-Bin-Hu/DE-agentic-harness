"""Task Level behavior (B4): user-chosen level, per-prompt budgets, subagent allow list.

Scenarios use real VS Code tool names (runSubagent, grep_search, read_file) and the hookSpecificOutput format.
"""

from __future__ import annotations

import concurrent.futures
import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from support import (
    HOOK,
    POLICY,
    HarnessTestCase,
    make_root,
    payload,
    pre_tool,
)

VERIFIER = {"agentName": "verifier", "prompt": "check it", "description": "check"}
GENERIC = {"prompt": "do this", "description": "work"}  # the built-in subagent has no agentName
GREP = {"query": "sandbox", "isRegexp": False}
LEVEL_SET = "python3 .harness/engine/cli.py level set --session-id s --level 2"


class TaskLevelTests(HarnessTestCase):
    def user_prompt(self, session_id: str, text: str = "start work") -> dict:
        return self.hook(payload("UserPromptSubmit", session_id, prompt=text))

    def pre(self, session_id: str, tool: str = "read_file", tool_input: Optional[dict] = None) -> dict:
        return self.hook(pre_tool(session_id, tool, tool_input))

    def decision(self, output: dict) -> str:
        return output.get("hookSpecificOutput", {}).get("permissionDecision", "")

    def reason(self, output: dict) -> str:
        return output["hookSpecificOutput"]["permissionDecisionReason"]

    def level(self, session_id: str) -> int:
        return self.session_state(session_id)["level"]

    def counters(self, session_id: str) -> dict:
        return self.task_level_state(session_id)["counters"]

    # --- policy -------------------------------------------------------------------------------

    def test_policy_has_markers_and_budgets_for_three_levels(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(policy["schema_version"], 2)
        self.assertEqual(policy["switch_markers"], {"1": ["/l1", "[L1]"], "2": ["/l2", "[L2]"]})
        budgets = [policy["levels"][str(level)]["budget_per_prompt"] for level in (1, 2, 3)]
        self.assertEqual([b["repository_searches"]["limit"] for b in budgets], [2, 8, 25])
        self.assertEqual([b["observed_tool_calls"]["limit"] for b in budgets], [15, 40, 120])
        self.assertEqual([b["repository_searches"]["on_exceed"] for b in budgets], ["deny", "warn", "warn"])
        self.assertEqual([b["observed_tool_calls"]["on_exceed"] for b in budgets], ["warn", "warn", "warn"])
        subagents = [policy["levels"][str(level)]["subagents"] for level in (1, 2, 3)]
        self.assertEqual([s["allowed"] for s in subagents], [[], ["verifier"], ["builder", "reviewer"]])
        self.assertEqual(subagents[1]["max_per_prompt"], 2)

    # --- switching the level (M2-1) -----------------------------------------------------------

    def test_a_new_session_is_level_1(self) -> None:
        self.user_prompt("fresh")
        self.assertEqual(self.level("fresh"), 1)

    def test_every_marker_switches_the_level(self) -> None:
        cases = [
            ("[L2] do it", 2), ("/l2 do it", 2), ("[l2] do it", 2), ("/L2 do it", 2), ("/l2", 2), ("[L2]do it", 2),
            ("  \n[L2] do it", 2), ("```\n[L2] do it\n```", 2),
        ]
        for index, (text, expected) in enumerate(cases):
            with self.subTest(text):
                session = f"marker-{index}"
                self.user_prompt(session, text)
                self.assertEqual(self.level(session), expected)
        for index, text in enumerate(("[L1] again", "/l1 again", "/l1")):
            with self.subTest(text):
                session = f"back-{index}"
                self.user_prompt(session, "[L2] first")
                self.user_prompt(session, text)
                self.assertEqual(self.level(session), 1)

    def test_text_that_is_not_a_marker_does_not_switch(self) -> None:
        for index, text in enumerate(("please use [L2] here", "/l2x do it", "[L3] do it", "[L] do it", "l2 do it", "")):
            with self.subTest(text):
                session = f"nomarker-{index}"
                self.user_prompt(session, text)
                self.assertEqual(self.level(session), 1)

    def test_the_level_stays_until_the_user_switches_again(self) -> None:
        self.user_prompt("sticky", "[L2] first")
        self.user_prompt("sticky", "a follow-up without a marker")
        self.assertEqual(self.level("sticky"), 2)
        self.user_prompt("sticky", "/l1 now small")
        self.assertEqual(self.level("sticky"), 1)

    def test_the_start_of_the_prompt_is_kept_for_diagnosis(self) -> None:
        self.user_prompt("head", "  /l2 " + "x" * 100)
        prompt = self.task_level_state("head")["prompt"]
        self.assertEqual(prompt["marker"], "/l2")
        self.assertEqual(prompt["head"], "/l2 " + "x" * 36)

    def test_the_switch_is_logged_with_its_source(self) -> None:
        self.user_prompt("log", "[L2] go")
        self.user_prompt("log", "[L2] again")  # no change, no record
        change = self.task_level_state("log")["level_changes"]
        self.assertEqual([(c["from_level"], c["to_level"], c["source"]) for c in change], [(1, 2, "marker")])

    def test_a_running_l3_request_ignores_markers(self) -> None:
        self.user_prompt("request")
        self.cli_json("level", "status", "--session-id", "request")  # make sure the state file exists
        path = self.state_file("request")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["active_request"] = "req-1"
        path.write_text(json.dumps(data), encoding="utf-8")
        output = self.user_prompt("request", "[L2] try to leave L3")
        self.assertEqual(self.level("request"), 1)
        context = output["additionalContext"]
        self.assertIn("L3", context)
        self.assertIn("[L2] 已被忽略", context)

    def test_a_marker_in_a_subagent_call_message_does_not_switch(self) -> None:
        """Layer 1 of hard conclusion 5: the UserPromptSubmit text equals the allowed runSubagent prompt."""
        self.verifier_default(True)
        self.user_prompt("child-msg", "[L2] start")
        message = "[L1] " + VERIFIER["prompt"]
        self.assertEqual(self.pre("child-msg", "runSubagent", {**VERIFIER, "prompt": message}), {})
        self.assertEqual(self.user_prompt("child-msg", message), {})
        self.assertEqual(self.level("child-msg"), 2)
        self.assertEqual(self.task_level_state("child-msg")["prompt"]["count"], 1)

    def test_a_marker_inside_the_subagent_window_does_not_switch(self) -> None:
        """Layer 2: anything between SubagentStart and SubagentStop is not the user."""
        self.user_prompt("window", "[L2] start")
        self.hook(payload("SubagentStart", "window", agent_id="a1", agent_type="verifier"))
        self.assertEqual(self.user_prompt("window", "[L1] text the model wrote"), {})
        self.assertEqual(self.level("window"), 2)
        self.hook(payload("SubagentStop", "window", agent_id="a1", agent_type="verifier", stop_hook_active=False))
        self.user_prompt("window", "[L1] now the user speaks")
        self.assertEqual(self.level("window"), 1)

    def test_verify_markers_cover_one_prompt(self) -> None:
        choices = [
            ("[L2] [no-verify] quick change", "off"),
            ("next change", ""),
            ("change it [No-Verify]", "off"),
            ("[L2] [verify] check it", "on"),
            ("[Verify] anywhere in the prompt", "on"),
            ("[verify] [no-verify] both", "off"),  # off wins
        ]
        for text, expected in choices:
            with self.subTest(text):
                self.user_prompt("verify", text)
                self.assertEqual(self.task_level_state("verify")["prompt"]["verify"], expected)

    # --- the user's prompt gets the rules (M2-3) ----------------------------------------------

    def test_the_prompt_rules_come_from_the_policy(self) -> None:
        context = self.user_prompt("rules")["additionalContext"]
        self.assertIn("L1", context)
        self.assertIn("搜索最多 2 次，超过会被拒绝", context)
        self.assertIn("工具调用建议不超过 15 次", context)
        self.assertIn("子 agent：不允许", context)
        self.assertIn("/l2", context)
        self.assertIn("level set", context)
        level2 = self.user_prompt("rules", "[L2] go")["additionalContext"]
        self.assertIn("L2", level2)
        self.assertIn("搜索建议不超过 8 次", level2)
        self.assertIn("子 agent：不允许", level2)  # the verifier is off by default
        self.assertIn("没有开启 verifier 复核", level2)
        self.assertIn("[verify]", level2)
        verified = self.user_prompt("rules", "[L2] [verify] go")["additionalContext"]
        self.assertIn("只允许 verifier，每条提示最多 2 次", verified)
        self.assertIn("调用 verifier 复核一次", verified)

    def test_the_rules_say_how_to_plan_for_the_level(self) -> None:
        """The prompt-file body never reaches the model on the SDK engine, so the hook says it."""
        self.assertIn("不写计划", self.user_prompt("plan")["additionalContext"])
        self.assertIn("先写一份短计划", self.user_prompt("plan", "[L2] go")["additionalContext"])

    def test_changing_the_policy_changes_the_rules_text(self) -> None:
        path = self.root / ".harness" / "policies" / "task-levels.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["levels"]["1"]["budget_per_prompt"]["repository_searches"]["limit"] = 5
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIn("搜索最多 5 次", self.user_prompt("policy")["additionalContext"])

    def test_session_start_injects_the_rules(self) -> None:
        output = self.hook(payload("SessionStart", "start", source="new", model="x"))
        self.assertIn("L1", output["additionalContext"])

    def test_l1_and_l2_rules_tell_the_orchestrator_not_to_stop(self) -> None:
        # S2 (B8): an orchestrator read "L1, no subagents" and stopped before `request new`.
        for text in ("start work", "[L2] start work"):
            context = self.user_prompt("orch-" + text[:2], text)["additionalContext"]
            self.assertIn("你是 orchestrator", context)
            self.assertIn("request new", context)
            self.assertIn("不要因为这里写着 L1 或 L2 而停下", context)

    # --- budgets (M2-3) -----------------------------------------------------------------------

    def test_l1_denies_the_third_search_and_says_what_to_do_next(self) -> None:
        self.user_prompt("l1-search")
        self.assertEqual(self.pre("l1-search", "grep_search", GREP), {})
        self.assertEqual(self.pre("l1-search", "file_search", {"query": "a"}), {})
        third = self.pre("l1-search", "semantic_search", {"query": "b"})
        self.assertEqual(self.decision(third), "deny")
        self.assertEqual(third["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertIn("L1 探索预算已用完", self.reason(third))
        self.assertIn("直接完成", self.reason(third))
        self.assertIn("/l2", self.reason(third))
        self.assertEqual(self.counters("l1-search")["repository_searches"], 2)  # the denied call did not happen
        self.assertEqual(self.counters("l1-search")["observed_tool_calls"], 2)
        # It stays denied, and reads are still fine.
        self.assertEqual(self.decision(self.pre("l1-search", "grep_search", GREP)), "deny")
        self.assertEqual(self.pre("l1-search", "read_file", {"filePath": "/a/b.md"}), {})

    def test_a_terminal_search_counts_and_is_denied_like_any_search(self) -> None:
        self.user_prompt("l1-terminal")
        self.pre("l1-terminal", "run_in_terminal", {"command": "git grep sandbox", "mode": "sync"})
        self.pre("l1-terminal", "run_in_terminal", {"command": "echo hi && rg sandbox .", "mode": "sync"})
        denied = self.pre("l1-terminal", "run_in_terminal", {"command": "find . -name x", "mode": "sync"})
        self.assertEqual(self.decision(denied), "deny")
        self.assertEqual(self.pre("l1-terminal", "run_in_terminal", {"command": "git status --short", "mode": "sync"}), {})

    def test_a_new_prompt_gives_a_new_budget(self) -> None:
        self.user_prompt("window-budget")
        self.pre("window-budget", "grep_search", GREP)
        self.pre("window-budget", "grep_search", GREP)
        self.assertEqual(self.decision(self.pre("window-budget", "grep_search", GREP)), "deny")
        self.user_prompt("window-budget", "a follow-up fix")
        self.assertEqual(self.counters("window-budget"), {"observed_tool_calls": 0, "repository_searches": 0, "subagents_created": 0})
        self.assertEqual(self.pre("window-budget", "grep_search", GREP), {})

    def test_l2_searches_over_the_limit_are_recorded_not_denied(self) -> None:
        self.user_prompt("l2-search", "[L2] investigate")
        for _ in range(9):
            self.assertEqual(self.pre("l2-search", "grep_search", GREP), {})
        state = self.task_level_state("l2-search")
        self.assertEqual(state["counters"]["repository_searches"], 9)
        self.assertEqual(state["exceeded"], ["repository_searches"])

    def test_l1_tool_calls_over_the_limit_are_recorded_not_denied(self) -> None:
        self.user_prompt("l1-calls")
        for _ in range(16):
            self.assertEqual(self.pre("l1-calls", "read_file", {"filePath": "/a/b.md"}), {})
        self.assertEqual(self.task_level_state("l1-calls")["exceeded"], ["observed_tool_calls"])

    def test_a_tool_call_budget_can_be_set_to_deny(self) -> None:
        path = self.root / ".harness" / "policies" / "task-levels.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["levels"]["1"]["budget_per_prompt"]["observed_tool_calls"] = {"limit": 2, "on_exceed": "deny"}
        path.write_text(json.dumps(data), encoding="utf-8")
        self.user_prompt("calls-deny")
        self.pre("calls-deny")
        self.pre("calls-deny")
        denied = self.pre("calls-deny")
        self.assertEqual(self.decision(denied), "deny")
        self.assertIn("工具调用预算已用完", self.reason(denied))

    def test_all_search_tools_are_counted_and_other_calls_only_as_calls(self) -> None:
        self.user_prompt("kinds", "[L2] go")
        for tool in ("grep_search", "file_search", "semantic_search"):
            self.pre("kinds", tool, {"query": "x"})
        self.pre("kinds", "read_file", {"filePath": "/a/b.md"})
        self.pre("kinds", "list_dir", {"path": "/a"})
        self.pre("kinds", "run_in_terminal", {"command": "git status --short", "mode": "sync"})
        self.assertEqual(self.counters("kinds"), {"observed_tool_calls": 6, "repository_searches": 3, "subagents_created": 0})

    # --- subagents (M2-5 allow list, B4 part) -------------------------------------------------

    def test_l1_denies_every_subagent_in_the_vscode_format(self) -> None:
        self.user_prompt("l1-sub")
        for tool_input in (VERIFIER, GENERIC):
            output = self.pre("l1-sub", "runSubagent", tool_input)
            body = output["hookSpecificOutput"]
            self.assertEqual(body["hookEventName"], "PreToolUse")
            self.assertEqual(body["permissionDecision"], "deny")
            self.assertIn("L1 不允许子 agent", body["permissionDecisionReason"])
            self.assertNotIn("permissionDecision", output)  # the top-level format is ignored by VS Code (B1, R4a)
        self.assertEqual(self.counters("l1-sub")["subagents_created"], 0)

    def test_l2_allows_only_the_verifier_by_agent_name(self) -> None:
        self.verifier_default(True)
        self.user_prompt("l2-sub", "[L2] go")
        self.assertEqual(self.pre("l2-sub", "runSubagent", VERIFIER), {})
        self.assertEqual(self.pre("l2-sub", "runSubagent", {**VERIFIER, "agentName": "Verifier"}), {})  # case does not matter
        for name in ("builder", "reviewer", "orchestrator", "probe-child"):
            denied = self.pre("l2-sub", "runSubagent", {**VERIFIER, "agentName": name})
            self.assertEqual(self.decision(denied), "deny", name)
            self.assertIn("只允许这些子 agent：verifier", self.reason(denied))
            self.assertIn(name, self.reason(denied))

    def test_the_generic_subagent_is_denied_at_every_level(self) -> None:
        """The built-in subagent has no agentName in PreToolUse; SubagentStart calls it `default` (B1)."""
        self.user_prompt("generic", "[L2] go")
        for tool_input in (GENERIC, {**GENERIC, "agentName": ""}, {**GENERIC, "agentName": "default"}):
            denied = self.pre("generic", "runSubagent", tool_input)
            self.assertEqual(self.decision(denied), "deny")
            self.assertIn("通用子 agent", self.reason(denied))
        self.assertEqual(self.counters("generic")["subagents_created"], 0)

    def test_l2_allows_the_verifier_at_most_twice_per_prompt(self) -> None:
        self.verifier_default(True)
        self.user_prompt("l2-max", "[L2] go")
        self.assertEqual(self.pre("l2-max", "runSubagent", VERIFIER), {})
        self.assertEqual(self.pre("l2-max", "runSubagent", VERIFIER), {})
        third = self.pre("l2-max", "runSubagent", VERIFIER)
        self.assertEqual(self.decision(third), "deny")
        self.assertIn("最多调用 2 次", self.reason(third))
        self.assertEqual(self.counters("l2-max")["subagents_created"], 2)
        self.user_prompt("l2-max", "next prompt")  # a new window
        self.assertEqual(self.pre("l2-max", "runSubagent", VERIFIER), {})

    def test_a_running_request_uses_the_l3_allow_list(self) -> None:
        self.user_prompt("l3-sub")
        path = self.state_file("l3-sub")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["active_request"] = "req-1"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.pre("l3-sub", "runSubagent", {**VERIFIER, "agentName": "builder"}), {})
        self.assertEqual(self.pre("l3-sub", "runSubagent", {**VERIFIER, "agentName": "reviewer"}), {})
        self.assertEqual(self.decision(self.pre("l3-sub", "runSubagent", VERIFIER)), "deny")

    # --- the agent cannot switch (M2-1) -------------------------------------------------------

    def test_an_agent_running_level_set_is_denied(self) -> None:
        self.user_prompt("agent-set")
        variants = [
            LEVEL_SET,
            "cd /x && python .harness/engine/cli.py level set --session-id s --level 2",
            "python3 .harness/engine/cli.py   level   set --session-id s --level 2",
            'python3 ".harness/engine/cli.py" "level" "set" --session-id s --level 2',
            "PYTHONPATH=. python3 .harness/engine/cli.py LEVEL SET --level 2",
            "python .harness\\engine\\cli.py level set --session-id s --level 2",
            "py -3 .\\.harness\\engine\\cli.py level set --level 2",
        ]
        for command in variants:
            with self.subTest(command):
                denied = self.pre("agent-set", "run_in_terminal", {"command": command, "mode": "sync"})
                self.assertEqual(self.decision(denied), "deny")
                self.assertIn("只有用户能切换 Level", self.reason(denied))
        self.assertEqual(self.level("agent-set"), 1)
        self.assertEqual(self.counters("agent-set")["observed_tool_calls"], 0)  # a denied call did not happen

    def test_level_status_and_other_commands_are_not_denied(self) -> None:
        self.user_prompt("agent-status")
        for command in (
            "python3 .harness/engine/cli.py level status --session-id s",
            "python3 .harness/engine/cli.py doctor",
            "echo level set",
            "git log --grep='level set'",
        ):
            with self.subTest(command):
                self.assertNotEqual(self.decision(self.pre("agent-status", "run_in_terminal", {"command": command, "mode": "sync"})), "deny")

    def test_the_user_can_set_the_level_from_the_cli(self) -> None:
        self.user_prompt("cli-set")
        state = self.cli_json("level", "set", "--session-id", "cli-set", "--level", "2")
        self.assertEqual(state["level"], 2)
        self.assertEqual(self.task_level_state("cli-set")["level_changes"][-1]["source"], "cli")
        self.assertEqual(self.cli_json("level", "set", "--session-id", "cli-set", "--level", "1")["level"], 1)

    def test_the_cli_cannot_set_level_3_or_an_unknown_level(self) -> None:
        for level in ("3", "9", "0"):
            with self.subTest(level):
                result = self.cli("level", "set", "--session-id", "cli-bad", "--level", level)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unknown level", result.stderr)

    def test_the_cli_refuses_to_set_a_level_during_an_l3_request(self) -> None:
        self.user_prompt("cli-request")
        path = self.state_file("cli-request")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["active_request"] = "req-1"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = self.cli("level", "set", "--session-id", "cli-request", "--level", "2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("L3 request", result.stderr)

    def test_the_old_lifecycle_commands_are_gone(self) -> None:
        for command in ("begin", "complete"):
            self.assertNotEqual(self.cli("level", command, "--session-id", "x", "--reason", "y").returncode, 0)

    # --- state --------------------------------------------------------------------------------

    def test_session_state_is_isolated_by_session(self) -> None:
        self.user_prompt("session-a", "[L2] a")
        self.user_prompt("session-b", "b")
        self.assertEqual(self.level("session-a"), 2)
        self.assertEqual(self.level("session-b"), 1)
        self.assertTrue(self.state_file("session-a").exists())
        self.assertTrue(self.state_file("session-b").exists())

    def test_state_from_the_first_engine_is_replaced_and_the_level_is_kept(self) -> None:
        self.user_prompt("old")
        path = self.state_file("old")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["level"] = 2
        data["modules"]["task_level"] = {
            "task": {"level": 2, "status": "active"},
            "counters": {"observed_tool_calls": 3, "repository_searches": 1, "subagents_created": 0},
            "warnings_emitted": [],
            "task_history": [],
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.pre("old"), {})
        state = self.task_level_state("old")
        self.assertEqual(state["version"], 4)
        self.assertEqual(self.level("old"), 2)
        self.assertEqual(state["counters"]["observed_tool_calls"], 1)
        self.assertEqual(self.log_lines("hook-errors.jsonl"), [])

    def test_concurrent_updates_do_not_lose_tool_counts(self) -> None:
        self.user_prompt("concurrent", "[L2] go")
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(lambda _: self.pre("concurrent"), range(10)))
        self.assertEqual(results, [{}] * 10)
        self.assertEqual(self.counters("concurrent")["observed_tool_calls"], 10)

    # --- the policy file ----------------------------------------------------------------------

    def test_a_marker_used_for_two_levels_is_rejected(self) -> None:
        from modules.task_level.policy import validate_policy

        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        policy["switch_markers"]["2"].append("/L1")
        with self.assertRaises(ValueError):
            validate_policy(policy)

    # --- fail-open ----------------------------------------------------------------------------

    def test_module_fails_open_when_the_policy_is_missing(self) -> None:
        missing = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, missing)
        make_root(missing, with_policy=False)
        self.env["HARNESS_ROOT"] = str(missing)
        self.assertEqual(self.pre("missing-policy"), {})
        errors = (missing / ".harness" / "runtime" / "logs" / "hook-errors.jsonl").read_text(encoding="utf-8")
        self.assertIn("module:task_level", errors)

    def test_module_fails_open_when_the_policy_is_the_old_schema(self) -> None:
        path = self.root / ".harness" / "policies" / "task-levels.json"
        path.write_text(json.dumps({"schema_version": 1, "levels": {}}), encoding="utf-8")
        self.assertEqual(self.pre("old-policy", "runSubagent", VERIFIER), {})
        self.assertIn("module:task_level", json.dumps(self.log_lines("hook-errors.jsonl")))

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
    import unittest

    unittest.main()
