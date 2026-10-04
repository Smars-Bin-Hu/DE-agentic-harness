"""Admin mode: a person switches it on for one session at a terminal; that session may then change guardrail files.

The hook cannot tell which agent is talking, so the admin agent file gives no rights. The session state does.
"""

from __future__ import annotations

import json
import unittest
from typing import Optional

from support import REPO, HarnessTestCase, payload, pre_tool

from core import guardrails
from modules.gate import commands


class _Sink:
    def write(self, _text: str) -> int:
        return 0

    def flush(self) -> None:
        pass


class AdminTestCase(HarnessTestCase):
    session = "admin-1"

    def setUp(self) -> None:
        super().setUp()
        self.base = str(self.root.resolve())
        self.prompt("hello")

    def prompt(self, text: str, session: Optional[str] = None) -> str:
        output = self.hook(payload("UserPromptSubmit", session or self.session, prompt=text))
        return self.context(output)

    def context(self, output: dict) -> str:
        return output.get("additionalContext") or output.get("hookSpecificOutput", {}).get("additionalContext", "")

    def switch_on(self, session: Optional[str] = None, code: Optional[str] = None) -> dict:
        asked = []

        def reader(question: str) -> str:
            asked.append(question)
            return code if code is not None else question.split("输入 ")[1].split("（")[0]

        return commands.admin_switch_on(self.root, session or self.session, reader=reader, interactive=True, out=_Sink())

    def write(self, relative: str, session: Optional[str] = None, tool: str = "create_file") -> dict:
        data = pre_tool(session or self.session, tool, {"filePath": f"{self.base}/{relative}", "content": "x"})
        data["cwd"] = self.base
        return self.hook(data)

    def term(self, command: str, session: Optional[str] = None) -> dict:
        data = pre_tool(session or self.session, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = self.base
        return self.hook(data)

    def decision(self, output: dict) -> str:
        return output.get("hookSpecificOutput", {}).get("permissionDecision", "")

    def reason(self, output: dict) -> str:
        return output["hookSpecificOutput"]["permissionDecisionReason"]


class SwitchTests(AdminTestCase):
    def test_it_is_for_a_person_at_a_terminal(self) -> None:
        with self.assertRaises(commands.CommandError):
            commands.admin_switch_on(self.root, self.session, reader=lambda _q: "x", interactive=False, out=_Sink())
        completed = self.cli("admin", "on", "--session-id", self.session)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("终端", completed.stderr)
        self.assertNotIn("admin", self.session_state(self.session))

    def test_a_wrong_code_switches_nothing_on(self) -> None:
        with self.assertRaises(commands.CommandError):
            self.switch_on(code="nope")
        self.assertNotIn("admin", self.session_state(self.session))
        self.assertEqual(self.decision(self.write(".harness/policies/gate.json")), "deny")

    def test_an_unknown_session_is_refused(self) -> None:
        with self.assertRaises(commands.CommandError) as caught:
            self.switch_on(session="nobody")
        self.assertIn("没有会话", str(caught.exception))

    def test_on_off_and_status(self) -> None:
        self.assertTrue(self.switch_on()["admin"])
        self.assertEqual([item["session_id"] for item in commands.admin_sessions(self.root)], [self.session])
        self.assertEqual(self.cli_json("admin", "status")["admin_sessions"][0]["session_id"], self.session)
        done = self.cli_json("admin", "off", "--session-id", self.session)
        self.assertEqual((done["admin"], done["was_on"]), (False, True))
        self.assertEqual(commands.admin_sessions(self.root), [])
        self.assertEqual(self.decision(self.write(".harness/policies/gate.json")), "deny")

    def test_an_agent_cannot_run_admin_on(self) -> None:
        for command in (
            f"python3 .harness/engine/cli.py admin on --session-id {self.session}",
            f"python .harness\\engine\\cli.py admin on --session-id {self.session}",
            f"harness admin on --session-id {self.session}",
        ):
            output = self.term(command)
            self.assertEqual(self.decision(output), "deny", command)
            self.assertIn("admin on", self.reason(output))
        self.switch_on()
        self.assertEqual(self.decision(self.term(f"python3 .harness/engine/cli.py admin on --session-id other")), "deny")

    def test_an_agent_may_switch_it_off(self) -> None:
        self.assertEqual(self.decision(self.term(f"python3 .harness/engine/cli.py admin off --session-id {self.session}")), "")

    def test_it_does_not_mix_with_a_request(self) -> None:
        self.cli_json("request", "new", "--title", "t", "--session-id", self.session)
        with self.assertRaises(commands.CommandError) as caught:
            self.switch_on()
        self.assertIn("L3 请求", str(caught.exception))

    def test_a_subagent_session_cannot_be_admin(self) -> None:
        path = self.state_file(self.session)
        state = json.loads(path.read_text(encoding="utf-8"))
        state["parent_session_id"] = "parent"
        path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(commands.CommandError) as caught:
            self.switch_on()
        self.assertIn("子 agent", str(caught.exception))


class GateTests(AdminTestCase):
    GUARDRAILS = (
        ".harness/policies/gate.json",
        ".harness/engine/hook.py",
        ".github/hooks/harness.json",
        ".harness/bin/harness",
        ".harness/registry.json",
        ".vscode/settings.json",
    )

    def test_guardrail_files_open_up_for_the_admin_session_only(self) -> None:
        self.prompt("hello", "other")
        for relative in self.GUARDRAILS:
            self.assertEqual(self.decision(self.write(relative)), "deny", relative)
        self.switch_on()
        for relative in self.GUARDRAILS:
            self.assertEqual(self.decision(self.write(relative)), "", relative)
            self.assertEqual(self.decision(self.write(relative, tool="replace_string_in_file")), "", relative)
            self.assertEqual(self.decision(self.write(relative, session="other")), "deny", relative)

    def test_the_runtime_folder_stays_closed(self) -> None:
        self.switch_on()
        for relative in (f".harness/runtime/state/vscode/{self.session}.json", ".harness/runtime/git-approvals.json", ".harness/runtime/logs/hook-errors.jsonl"):
            output = self.write(relative)
            self.assertEqual(self.decision(output), "deny", relative)
            self.assertIn("admin 模式下也不能改", self.reason(output))
        output = self.term("rm .harness/runtime/git-approvals.json")
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("admin 模式下也不能改", self.reason(output))
        self.assertEqual(self.decision(self.term("echo x > .harness/runtime/state/vscode/a.json")), "deny")

    def test_terminal_writes_to_guardrail_files_open_up(self) -> None:
        command = "sed -i '' 's/a/b/' .harness/policies/gate.json"
        self.assertEqual(self.decision(self.term(command)), "deny")
        self.switch_on()
        self.assertEqual(self.decision(self.term(command)), "")
        self.assertEqual(self.decision(self.term("mv .harness/engine/a.py .harness/engine/b.py")), "")

    def test_the_other_rules_stay(self) -> None:
        self.switch_on()
        self.assertEqual(self.decision(self.write(".workspace/reports/r.md")), "deny")
        self.assertEqual(self.decision(self.write(".workspace/sandbox/requests/r1/request.json")), "deny")
        self.assertEqual(self.decision(self.write(".git/config")), "deny")
        self.assertEqual(self.decision(self.term("rm -rf /")), "deny")
        self.assertEqual(self.decision(self.term("python3 .harness/engine/cli.py approve-command")), "deny")
        self.assertEqual(self.decision(self.term("python3 .harness/engine/cli.py request approve-promote --request r")), "deny")
        self.assertEqual(self.decision(self.term("curl https://example.com")), "ask")
        self.assertEqual(self.decision(self.term(f"python3 .harness/engine/cli.py level set --session-id {self.session} --level 2")), "deny")

    def test_a_policy_can_keep_more_closed_but_cannot_open_the_runtime_folder(self) -> None:
        override = self.root / ".harness" / "policies" / "gate.override.json"
        override.write_text(json.dumps({"admin_locked_paths": [".github/hooks/**"]}), encoding="utf-8")
        self.switch_on()
        self.assertEqual(self.decision(self.write(".github/hooks/harness.json")), "deny")
        self.assertEqual(self.decision(self.write(".harness/runtime/git-approvals.json")), "deny")
        self.assertEqual(self.decision(self.write(".harness/policies/gate.json")), "")
        self.assertEqual(guardrails.admin_locked({}), [".harness/runtime/**"])

    def test_the_log_marks_admin_calls(self) -> None:
        self.write("notes.txt")
        self.switch_on()
        self.write("notes.txt")
        rows = [row for row in self.session_log(self.session) if row["event"] == "PreToolUse"]
        self.assertEqual([row.get("admin", False) for row in rows], [False, True])


class LevelTests(AdminTestCase):
    def search(self) -> dict:
        return self.hook(pre_tool(self.session, "grep_search", {"query": "x"}))

    def test_the_rules_say_admin_mode_and_markers_do_nothing(self) -> None:
        self.assertIn("Task Level：L1", self.prompt("hello"))
        self.switch_on()
        text = self.prompt("/l2 do it")
        self.assertIn("admin 模式：已开", text)
        self.assertNotIn("Task Level：L", text)
        self.assertIn(self.session, text)
        self.assertIn(".harness/runtime/**", text)
        self.assertEqual(self.session_state(self.session)["level"], 1)
        self.assertIn("admin 模式：已开", self.context(self.hook(payload("SessionStart", self.session))))

    def test_no_budget(self) -> None:
        for _ in range(2):
            self.assertEqual(self.decision(self.search()), "")
        self.assertEqual(self.decision(self.search()), "deny")
        self.switch_on()
        self.prompt("go")
        for _ in range(30):
            self.assertEqual(self.decision(self.search()), "")
        state = self.task_level_state(self.session)
        self.assertEqual(state["counters"]["repository_searches"], 30)
        self.assertEqual(state["exceeded"], [])

    def test_no_subagent(self) -> None:
        self.switch_on()
        for name in ("verifier", "builder", ""):
            output = self.hook(pre_tool(self.session, "runSubagent", {"agentName": name, "prompt": "p", "description": "d"}))
            self.assertEqual(self.decision(output), "deny", name)
            self.assertIn("admin 模式不允许子 agent", self.reason(output))

    def test_admin_is_never_a_subagent(self) -> None:
        for marker in ("", "/l2 [verify] "):
            self.prompt(marker + "go")
            output = self.hook(pre_tool(self.session, "runSubagent", {"agentName": "admin", "prompt": "p", "description": "d"}))
            self.assertEqual(self.decision(output), "deny", marker)

    def test_no_request_and_no_task(self) -> None:
        self.switch_on()
        completed = self.cli("request", "new", "--title", "t", "--session-id", self.session)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("admin 模式", completed.stderr)
        (self.root / ".workspace" / "current_tasks" / "demo").mkdir(parents=True)
        completed = self.cli("task", "start", "--task", ".workspace/current_tasks/demo", "--session-id", self.session)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("admin 模式", completed.stderr)

    def test_stop_asks_for_no_verifier(self) -> None:
        self.verifier_default(True)
        self.hook(payload("UserPromptSubmit", self.session, prompt="/l2 edit"))
        self.switch_on()
        self.prompt("edit")
        self.write("notes.txt", tool="replace_string_in_file")
        self.hook({**pre_tool(self.session, "replace_string_in_file", {"filePath": f"{self.base}/notes.txt"}), "hook_event_name": "PostToolUse", "tool_response": "ok"})
        output = self.hook(payload("Stop", self.session, stop_hook_active=False))
        self.assertNotEqual(output.get("decision"), "block")


class AgentFileTests(unittest.TestCase):
    def test_the_admin_agent_can_be_chosen_and_calls_no_subagent(self) -> None:
        text = (REPO / ".github" / "agents" / "admin.agent.md").read_text(encoding="utf-8")
        head = text.split("---")[1]
        self.assertIn("name: admin", head)
        self.assertNotIn("user-invocable: false", head)
        self.assertIn("agents: []", head)
        self.assertNotIn("'agent'", head)
        self.assertIn("admin on", text)

    def test_no_level_allows_admin_as_a_subagent(self) -> None:
        policy = json.loads((REPO / ".harness" / "policies" / "task-levels.json").read_text(encoding="utf-8"))
        for level, body in policy["levels"].items():
            self.assertNotIn("admin", body["subagents"]["allowed"], level)
        for path in (REPO / ".github" / "agents").glob("*.agent.md"):
            head = path.read_text(encoding="utf-8").split("---")[1]
            self.assertNotRegex(head, r"agents:.*admin", path.name)


if __name__ == "__main__":
    unittest.main()
