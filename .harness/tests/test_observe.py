"""Observe (B9-A, M5-2): one log file per session, who decided, what a refusal was about, stats and prune."""

from __future__ import annotations

import json
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from support import HOOK, HarnessTestCase, payload, post_tool, pre_tool

GUARD = ".harness/policies/gate.json"
GREP = {"query": "sandbox", "isRegexp": False}
EDIT = {"filePath": "/w/a.txt", "oldString": "a", "newString": "b"}


class ObserveCase(HarnessTestCase):
    def prompt(self, sid: str, text: str = "work") -> Dict[str, Any]:
        return self.hook(payload("UserPromptSubmit", sid, prompt=text))

    def path(self, relative: str) -> str:
        return str(self.root / relative)

    def last(self, sid: str) -> Dict[str, Any]:
        return self.session_log(sid)[-1]

    def policy_file(self) -> Path:
        return self.root / ".harness" / "policies" / "observe.json"

    def set_policy(self, **changes: Any) -> None:
        data = json.loads(self.policy_file().read_text(encoding="utf-8"))
        data.update(changes)
        self.policy_file().write_text(json.dumps(data), encoding="utf-8")

    def logs(self) -> Path:
        return self.root / ".harness" / "runtime" / "logs"


class SessionLogTests(ObserveCase):
    def test_every_session_has_its_own_file_and_there_is_no_shared_call_log(self) -> None:
        self.prompt("one")
        self.prompt("two")
        self.assertTrue((self.logs() / "vscode" / "one.jsonl").is_file())
        self.assertTrue((self.logs() / "vscode" / "two.jsonl").is_file())
        self.assertFalse((self.logs() / "hook-calls.jsonl").exists())
        self.assertEqual({row["session_id"] for row in self.session_log("one")}, {"one"})

    def test_a_line_has_the_event_the_level_the_modules_the_decision_and_the_time(self) -> None:
        self.prompt("fields")
        row = self.last("fields")
        for key in ("at", "surface", "engine", "event", "session_id", "level", "modules", "decision", "ms", "pid"):
            self.assertIn(key, row)
        self.assertEqual((row["event"], row["level"], row["decision"]), ("UserPromptSubmit", 1, "context"))
        self.assertIn("task_level", row["modules"])

    def test_the_level_in_the_line_is_the_level_of_the_session(self) -> None:
        self.prompt("lv", "[L2] work")
        self.assertEqual(self.last("lv")["level"], 2)

    def test_an_allowed_call_leaves_no_paths_no_command_and_no_reason(self) -> None:
        self.hook(pre_tool("allowed", "read_file", {"filePath": self.path("secret/customer.sql")}))
        row = self.last("allowed")
        self.assertEqual(row["decision"], "none")
        self.assertEqual(row["tool_kind"], "read")
        for key in ("target", "reason", "judge", "by"):
            self.assertNotIn(key, row)
        self.assertNotIn("customer", json.dumps(row))

    def test_a_denied_call_names_the_module_the_paths_and_the_reason(self) -> None:
        self.hook(pre_tool("denied", "create_file", {"filePath": self.path(GUARD), "content": "x"}))
        row = self.last("denied")
        self.assertEqual((row["decision"], row["judge"], row["by"]), ("deny", "rule", ["gate"]))
        self.assertIn("guardrail", row["reason"])
        self.assertEqual(row["target"]["paths"], [self.path(GUARD)])

    def test_a_command_sent_to_a_person_is_recorded_as_a_human_judgement(self) -> None:
        self.hook(pre_tool("asked", "run_in_terminal", {"command": "rm build/old.txt"}))
        row = self.last("asked")
        self.assertEqual((row["decision"], row["judge"], row["by"]), ("ask", "human", ["gate"]))
        self.assertEqual(row["target"]["command"], "rm build/old.txt")

    def test_a_budget_denial_is_marked_as_one(self) -> None:
        self.prompt("budget")
        for _ in range(2):
            self.hook(pre_tool("budget", "grep_search", GREP))
        self.hook(pre_tool("budget", "grep_search", GREP))
        row = self.last("budget")
        self.assertEqual((row["decision"], row["kind"], row["by"]), ("deny", "budget", ["task_level"]))

    def test_the_verdict_of_a_verifier_call_is_recorded_with_the_verifier_as_judge(self) -> None:
        self.prompt("verdict", "[L2] [verify] change a file")
        call = {"agentName": "verifier", "prompt": "check", "description": "check"}
        self.hook(post_tool("verdict", "runSubagent", call, "VERDICT: FAIL\n- missing"))
        row = self.last("verdict")
        self.assertEqual((row["judge"], row["verdict"]), ("verifier", "FAIL"))

    def test_a_repeated_denial_keeps_the_circuit_breaker_entry(self) -> None:
        for _ in range(3):
            self.hook(pre_tool("breaker", "create_file", {"filePath": self.path(GUARD), "content": "x"}))
        row = self.last("breaker")
        self.assertEqual(row["denial"]["count"], 3)
        self.assertTrue(row["denial"]["tripped"])
        self.assertEqual(row["by"], ["gate"])

    def test_the_model_and_transcript_of_a_session_start_are_kept(self) -> None:
        self.hook(payload("SessionStart", "start", source="new", model="claude-opus-5.5"))
        row = self.last("start")
        self.assertEqual(row["model"], "claude-opus-5.5")
        self.assertIn("transcript", row)

    def test_a_long_command_and_a_long_reason_are_cut_to_the_policy_size(self) -> None:
        self.set_policy(max_text_chars=40)
        self.hook(pre_tool("clip", "run_in_terminal", {"command": "rm " + "x" * 500}))
        row = self.last("clip")
        self.assertEqual(len(row["target"]["command"]), 41)
        self.assertTrue(row["target"]["command"].endswith("…"))
        self.assertLessEqual(len(row["reason"]), 41)

    def test_a_session_id_cannot_leave_the_log_folder(self) -> None:
        self.prompt("../../escape")
        files = [path.relative_to(self.logs()).as_posix() for path in self.logs().rglob("*.jsonl")]
        self.assertTrue(all(name.startswith("vscode/") and ".." not in name for name in files), files)
        self.assertFalse((self.root / "escape.jsonl").exists())

    def test_an_unreadable_input_goes_to_the_error_log_only(self) -> None:
        completed = self.run_script(HOOK, stdin="not json")
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(list(self.logs().glob("*/*.jsonl")), [])
        self.assertTrue(self.log_lines("hook-errors.jsonl"))

    def test_a_subagent_session_records_its_parent(self) -> None:
        self.prompt("parent")
        self.hook(payload("SubagentStart", "parent", agent_id="a1", agent_type="builder"))
        row = self.last("parent")
        self.assertEqual((row["event"], row["agent_type"]), ("SubagentStart", "builder"))


class SwitchTests(ObserveCase):
    def disable(self) -> None:
        path = self.root / ".harness" / "registry.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["modules"]["observe"]["enabled"] = False
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_with_the_module_off_nothing_is_logged_and_the_hook_still_works(self) -> None:
        self.disable()
        output = self.hook(pre_tool("off", "create_file", {"filePath": self.path(GUARD), "content": "x"}))
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(list(self.logs().glob("*/*.jsonl")), [])

    def test_a_broken_policy_falls_back_to_the_defaults_and_the_log_goes_on(self) -> None:
        self.policy_file().write_text("{broken", encoding="utf-8")
        self.prompt("broken-policy")
        self.assertEqual(len(self.session_log("broken-policy")), 1)

    def test_a_registry_without_observe_logs_nothing(self) -> None:
        path = self.root / ".harness" / "registry.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["modules"]["observe"]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.prompt("no-entry")
        self.assertEqual(list(self.logs().glob("*/*.jsonl")), [])


class CaptureTests(ObserveCase):
    def captures(self) -> List[Path]:
        return sorted((self.root / ".harness" / "runtime" / "capture").rglob("*.json"))

    def test_capture_is_off_by_default(self) -> None:
        self.prompt("cap-off")
        self.assertEqual(self.captures(), [])

    def test_capture_saves_the_raw_input_and_the_output_and_only_the_names_of_variables(self) -> None:
        self.set_policy(capture={"enabled": True})
        self.env["HARNESS_TEST_SECRET"] = "hunter2"
        self.prompt("cap-on", "hello")
        files = self.captures()
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["argv_event"], "UserPromptSubmit")
        self.assertIn('"prompt": "hello"', data["stdin_raw"])
        self.assertEqual(data["stdin_json"]["prompt"], "hello")
        self.assertIn("HARNESS_TEST_SECRET", data["env_names"])
        self.assertNotIn("hunter2", json.dumps(data))
        self.assertIn("additionalContext", json.dumps(data["hook_output"]))


class StatsTests(ObserveCase):
    def stats(self, *arguments: str) -> Dict[str, Any]:
        return self.cli_json("stats", *arguments)

    def build(self) -> None:
        self.prompt("a", "[L2] work")
        self.prompt("a", "more")
        self.hook(pre_tool("a", "read_file", {"filePath": "/w/a.txt"}))
        self.hook(pre_tool("a", "run_in_terminal", {"command": "rm x"}))
        self.prompt("b")
        for _ in range(3):
            self.hook(pre_tool("b", "grep_search", GREP))
        self.hook(pre_tool("b", "create_file", {"filePath": self.path(GUARD), "content": "x"}))

    def test_counts_prompts_per_level_refusals_asks_and_budget_denials(self) -> None:
        self.build()
        result = self.stats()
        self.assertEqual(result["sessions"], 2)
        self.assertEqual(result["prompts_by_level"], {"L1": 1, "L2": 2})
        self.assertEqual(result["denied_by_module"], {"gate": 1, "task_level": 1})
        self.assertEqual(result["budget_denials"], 1)
        self.assertEqual(result["asked_by_module"], {"gate": 1})
        self.assertEqual(result["tool_calls_by_level"], {"L1": 4, "L2": 2})

    def write_rows(self, rows: list) -> None:
        folder = self.logs() / "vscode"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "dup.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def row(self, second: str, pid: int, tool: str = "read_file") -> Dict[str, Any]:
        return {"at": f"2026-10-03T10:00:{second}+00:00", "pid": pid, "event": "PreToolUse", "tool_name": tool, "tool_kind": "read",
                "decision": "allow", "from_subagent": False, "level": 1}

    def test_the_same_call_from_two_processes_at_once_is_a_possible_double_run(self) -> None:
        self.write_rows([self.row("01.000000", 11), self.row("01.050000", 12)])
        self.assertEqual(self.stats()["possible_double_runs"], 1)

    def test_other_pairs_are_not_double_runs(self) -> None:
        for rows in (
            [self.row("01.000000", 11), self.row("01.050000", 11)],                     # one process
            [self.row("01.000000", 11), self.row("01.050000", 12, "grep_search")],      # another tool
            [self.row("01.000000", 11), self.row("03.000000", 12)],                     # two seconds apart
        ):
            self.write_rows(rows)
            self.assertEqual(self.stats()["possible_double_runs"], 0)

    def test_hook_time_is_counted_per_event(self) -> None:
        self.build()
        result = self.stats()
        self.assertEqual(result["hook_time"]["calls"], result["calls"])
        self.assertGreater(result["hook_time"]["max_ms"], 0)
        self.assertEqual(result["hook_time_by_event"]["UserPromptSubmit"]["calls"], 3)

    def test_one_session_only(self) -> None:
        self.build()
        result = self.stats("--session-id", "b")
        self.assertEqual((result["sessions"], result["prompts_by_level"]), (1, {"L1": 1}))

    def test_verifier_verdicts_and_started_subagents(self) -> None:
        self.prompt("v", "[L2] [verify] work")
        call = {"agentName": "verifier", "prompt": "check", "description": "check"}
        self.hook(post_tool("v", "runSubagent", call, "VERDICT: PASS\n- ok"))
        self.hook(post_tool("v", "runSubagent", call, "VERDICT: FAIL\n- no"))
        self.hook(payload("SubagentStart", "v", agent_id="a1", agent_type="verifier"))
        result = self.stats()
        self.assertEqual(result["verifier_verdicts"], {"PASS": 1, "FAIL": 1})
        self.assertEqual(result["subagents_started"], {"verifier": 1})

    def test_days_keeps_only_recent_calls(self) -> None:
        self.build()
        path = self.logs() / "vscode" / "a.jsonl"
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            row["at"] = old
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        result = self.stats("--days", "5")
        self.assertEqual(result["sessions"], 1)
        self.assertEqual(self.stats("--days", "30")["sessions"], 2)

    def test_hook_errors_follow_the_days_window(self) -> None:
        self.run_script(HOOK, stdin="not json")
        self.assertEqual(self.stats()["hook_errors"], 1)
        path = self.logs() / "hook-errors.jsonl"
        row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        row["at"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.assertEqual(self.stats("--days", "5")["hook_errors"], 0)
        self.assertEqual(self.stats("--days", "30")["hook_errors"], 1)

    def test_no_logs_gives_zeros(self) -> None:
        result = self.stats()
        self.assertEqual((result["sessions"], result["calls"], result["hook_time"]["calls"]), (0, 0, 0))

    def test_a_half_written_last_line_is_skipped(self) -> None:
        self.prompt("half")
        with (self.logs() / "vscode" / "half.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"event": "Stop", "ms":')
        self.assertEqual(self.stats()["calls"], 1)


class PruneTests(ObserveCase):
    def age(self, session: str, days: float) -> None:
        stamp = time.time() - days * 86400
        os.utime(self.logs() / "vscode" / f"{session}.jsonl", (stamp, stamp))

    def test_deletes_only_logs_older_than_the_days_and_nothing_else(self) -> None:
        self.prompt("old")
        self.prompt("new")
        self.age("old", 40)
        result = self.cli_json("logs", "prune", "--days", "30")
        self.assertEqual(result["deleted"], ["vscode/old.jsonl"])
        self.assertEqual(result["kept"], 1)
        self.assertFalse((self.logs() / "vscode" / "old.jsonl").exists())
        self.assertTrue((self.logs() / "vscode" / "new.jsonl").exists())
        self.assertTrue((self.root / ".harness" / "runtime" / "state" / "vscode" / "old.json").exists())

    def test_dry_run_deletes_nothing(self) -> None:
        self.prompt("old")
        self.age("old", 40)
        result = self.cli_json("logs", "prune", "--days", "30", "--dry-run")
        self.assertEqual(result["would_delete"], ["vscode/old.jsonl"])
        self.assertTrue((self.logs() / "vscode" / "old.jsonl").exists())

    def test_the_error_log_is_never_pruned(self) -> None:
        self.run_script(HOOK, stdin="not json")
        stamp = time.time() - 90 * 86400
        os.utime(self.logs() / "hook-errors.jsonl", (stamp, stamp))
        self.cli_json("logs", "prune", "--days", "1")
        self.assertTrue((self.logs() / "hook-errors.jsonl").exists())

    def test_days_must_be_one_or_more(self) -> None:
        completed = self.cli("logs", "prune", "--days", "0")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("--days", completed.stderr)

    def test_an_agent_running_prune_is_sent_to_the_person(self) -> None:
        self.assertEqual(self.hook(pre_tool("agent", "run_in_terminal", {"command": "harness logs prune --days 1"}))["hookSpecificOutput"]["permissionDecision"], "ask")  # the short command too
        output = self.hook(pre_tool("agent", "run_in_terminal", {"command": "python3 .harness/engine/cli.py logs prune --days 1"}))
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "ask")


if __name__ == "__main__":
    unittest.main()
