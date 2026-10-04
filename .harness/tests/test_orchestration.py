"""B8: a subagent call in L3 needs a dispatch (M4-4), the subagent is told its package (M4-7), the agent files and
the model series rule (M4-5), the orchestration skill (M4-6)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from support import CLI, REPO, payload

from core.state import update_state
from test_doctor import copy_repo
from test_request import SESSION, RequestCase

AGENTS = REPO / ".github" / "agents"
SDK = REPO / ".harness" / "eval" / "fixtures" / "hooks" / "copilot-sdk" / "payloads"


def frontmatter(path: Path) -> Dict[str, str]:
    text = path.read_text(encoding="utf-8")
    block = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL).group(1)
    return {line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in block.splitlines() if ":" in line and not line.startswith(" ")}


class DispatchGateTests(RequestCase):
    def call(self, role: str, session: str = SESSION, tool: str = "runSubagent") -> Dict[str, Any]:
        data = payload("PreToolUse", session, tool_name=tool, tool_input={"agentName": role, "prompt": f"do the {role} job", "description": role}, tool_use_id="t1")
        return self.hook(data)

    def decision(self, output: Dict[str, Any]) -> str:
        return output.get("hookSpecificOutput", {}).get("permissionDecision", "")

    def reason(self, output: Dict[str, Any]) -> str:
        return output["hookSpecificOutput"]["permissionDecisionReason"]

    def ready_builder(self) -> str:
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        return request_id

    def test_a_call_before_dispatch_is_refused_and_says_which_command(self) -> None:
        request_id = self.ready_builder()
        output = self.call("builder")
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("必须先 dispatch", self.reason(output))
        self.assertIn(f"dispatch --request {request_id} --role builder", self.reason(output))

    def test_after_dispatch_one_call_is_allowed_and_uses_the_record_up(self) -> None:
        request_id = self.ready_builder()
        self.dispatch(request_id, "builder")
        self.assertEqual(self.request(request_id)["pending_dispatch"][0]["role"], "builder")
        self.assertEqual(self.call("builder"), {})
        self.assertEqual(self.request(request_id)["pending_dispatch"], [])
        self.hook(payload("SubagentStart", SESSION, agent_id="a-builder", agent_type="builder"))  # the call really started
        output = self.call("builder")
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("已经调用过了", self.reason(output))
        self.assertEqual(self.check(request_id)["problems"], [])

    def test_a_call_the_tool_refused_can_be_made_again_without_a_new_dispatch(self) -> None:
        """The tool checks its arguments after the hook. A missing required one means the subagent never started."""
        request_id = self.ready_builder()
        self.dispatch(request_id, "builder")
        self.assertEqual(self.call("builder"), {})  # passes the hook; the tool then refuses it, no SubagentStart follows
        self.assertEqual(self.call("builder"), {})  # the retry is allowed
        self.assertEqual(self.call("builder"), {})  # and again
        self.hook(payload("SubagentStart", SESSION, agent_id="a-builder", agent_type="builder"))
        self.assertEqual(self.decision(self.call("builder")), "deny")  # it started once: no second run for this dispatch

    def test_a_retry_is_only_for_the_role_and_attempt_that_never_started(self) -> None:
        request_id = self.ready_builder()
        self.dispatch(request_id, "builder")
        self.assertEqual(self.call("builder"), {})
        self.assertEqual(self.decision(self.call("reviewer")), "deny")  # no dispatch for the reviewer
        self.assertEqual(self.request(request_id)["pending_dispatch"], [])

    def test_a_dispatch_for_one_role_does_not_open_the_other(self) -> None:
        request_id = self.ready_builder()
        self.dispatch(request_id, "builder")
        output = self.call("reviewer")
        self.assertEqual(self.decision(output), "deny")
        self.assertIn(f"dispatch --request {request_id} --role reviewer", self.reason(output))
        self.assertEqual(len(self.request(request_id)["pending_dispatch"]), 1)  # builder's record is still there

    def test_a_whole_attempt_goes_through(self) -> None:
        request_id = self.new_request()
        for number in (1, 2):
            self.attempt(request_id)
            self.fill_assignment(request_id, number, "builder")
            self.dispatch(request_id, "builder")
            self.assertEqual(self.call("builder"), {})
            self.output(request_id, number, "builder", "src/slug.py")
            self.submit(request_id, "builder", "passed", "--output", "src/slug.py")
            self.fill_assignment(request_id, number, "reviewer")
            self.dispatch(request_id, "reviewer")
            self.assertEqual(self.call("reviewer"), {})
            self.output(request_id, number, "reviewer", "t.log")
            self.submit(request_id, "reviewer", "failed", "--evidence", "t.log", "--blocker", "no")
        self.assertEqual(self.request(request_id)["pending_dispatch"], [])
        self.assertEqual(self.check(request_id)["problems"], [])

    def test_other_names_and_the_generic_subagent_are_refused_in_l3(self) -> None:
        self.ready_builder()
        for name in ("verifier", "explore", "", "default"):
            with self.subTest(name):
                self.assertEqual(self.decision(self.call(name)), "deny")

    def test_a_subagent_session_cannot_call_a_subagent(self) -> None:
        request_id = self.ready_builder()
        self.dispatch(request_id, "builder")
        update_state(self.root, "vscode", SESSION, lambda state: state.update(parent_session_id="some-parent"))
        output = self.call("builder")
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("不能再调用子 agent", self.reason(output))
        self.assertEqual(len(self.request(request_id)["pending_dispatch"]), 1)

    def test_builder_and_reviewer_are_refused_at_l1_and_l2(self) -> None:
        for marker in ("[L1]", "[L2]"):
            session = f"plain-{marker}"
            self.hook(payload("UserPromptSubmit", session, prompt=f"{marker} work"))
            for role in ("builder", "reviewer"):
                with self.subTest(f"{marker} {role}"):
                    self.assertEqual(self.decision(self.call(role, session)), "deny")

    def test_a_concluded_request_no_longer_opens_the_door(self) -> None:
        request_id = self.ready_builder()
        self.dispatch(request_id, "builder")
        self.run_cli("request", "set-status", "--request", request_id, "--status", "abandoned", "--reason", "x")
        self.assertEqual(self.decision(self.call("builder")), "deny")  # back at L1: no subagents at all

    def test_the_sdk_engine_denies_in_the_top_level_format(self) -> None:
        request_id = self.ready_builder()
        data = json.loads((SDK / "PreToolUse.Agent.json").read_text(encoding="utf-8"))
        data["session_id"] = SESSION
        data["tool_input"]["agent_type"] = "builder"
        output = self.hook(data)
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn(f"--request {request_id}", output["permissionDecisionReason"])
        self.dispatch(request_id, "builder")
        self.assertEqual(self.hook(data), {})


class SubagentStartTests(RequestCase):
    def start(self, role: str, session: str = SESSION) -> Dict[str, Any]:
        return self.hook(payload("SubagentStart", session, agent_id=f"a-{role}", agent_type=role))

    def called(self, role: str) -> str:
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.dispatch(request_id, "builder")
        if role == "reviewer":
            self.output(request_id, 1, "builder", "src/slug.py")
            self.submit(request_id, "builder", "passed", "--output", "src/slug.py")
            self.fill_assignment(request_id, 1, "reviewer")
            self.dispatch(request_id, "reviewer")
        self.hook(payload("PreToolUse", SESSION, tool_name="runSubagent", tool_input={"agentName": role, "prompt": "p"}, tool_use_id="t"))
        return request_id

    def test_the_called_subagent_is_told_its_assignment_and_output_folder(self) -> None:
        request_id = self.called("builder")
        context = self.start("builder")["hookSpecificOutput"]["additionalContext"]
        base = f".workspace/sandbox/requests/{request_id}"
        self.assertIn(f"{base}/handoffs/orchestrator/attempt-001/to-builder/assignment.md", context)
        self.assertIn("manifest.json", context)
        self.assertIn(f"{base}/builder/outputs/attempt-001/", context)
        self.assertIn("mkdir -p", context)
        self.assertIn(f"handoff submit --request {request_id} --role builder", context)
        self.assertIn("第 1 轮的 builder", context)

    def test_the_reviewer_gets_its_own_package(self) -> None:
        request_id = self.called("reviewer")
        context = self.start("reviewer")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("to-reviewer/assignment.md", context)
        self.assertIn("reviewer/outputs/attempt-001/", context)
        self.assertNotIn("to-builder", context)

    def test_the_context_is_given_once(self) -> None:
        self.called("builder")
        self.assertIn("additionalContext", self.start("builder")["hookSpecificOutput"])
        self.assertEqual(self.start("builder"), {})

    def test_a_subagent_that_was_not_called_through_the_gate_gets_nothing(self) -> None:
        self.new_request()
        self.assertEqual(self.start("builder"), {})
        self.assertEqual(self.start("verifier"), {})

    def test_outside_l3_nothing_is_injected(self) -> None:
        self.hook(payload("UserPromptSubmit", "plain", prompt="[L2] x"))
        self.assertEqual(self.start("builder", "plain"), {})

    def test_the_sdk_engine_gets_it_in_the_top_level_format(self) -> None:
        request_id = self.called("builder")
        data = json.loads((SDK / "SubagentStart.json").read_text(encoding="utf-8"))
        data["sessionId"] = SESSION
        data["agentName"] = "builder"
        output = self.hook(data)
        self.assertIn(request_id, output["additionalContext"])
        self.assertNotIn("hookSpecificOutput", output)


class AgentFileTests(unittest.TestCase):
    def test_the_three_roles_are_configured_as_designed(self) -> None:
        orchestrator, builder, reviewer = (frontmatter(AGENTS / f"{name}.agent.md") for name in ("orchestrator", "builder", "reviewer"))
        for name, data in (("orchestrator", orchestrator), ("builder", builder), ("reviewer", reviewer)):
            self.assertEqual(data["name"], name)
            self.assertNotIn("disable-model-invocation", data)  # it does not stop a call (B1); the hook does
        self.assertNotIn("user-invocable", orchestrator)  # the user picks it in the list
        for data in (builder, reviewer):
            self.assertEqual(data["user-invocable"], "false")
            self.assertEqual(data["agents"], "[]")
            self.assertNotIn("'agent'", data["tools"])
        self.assertEqual(orchestrator["agents"], "['builder', 'reviewer']")
        self.assertIn("'agent'", orchestrator["tools"])
        for data in (orchestrator, builder, reviewer):
            self.assertIn("'execute'", data["tools"])  # the CLI runs in the terminal

    def test_the_models_follow_the_split(self) -> None:
        names = {name: frontmatter(AGENTS / f"{name}.agent.md")["model"] for name in ("orchestrator", "builder", "reviewer")}
        self.assertIn("Opus", names["orchestrator"])
        self.assertIn("Opus", names["reviewer"])
        self.assertIn("Sonnet", names["builder"])
        self.assertNotIn("Opus", names["builder"])
        self.assertNotIn("Sonnet", names["reviewer"])

    def test_every_cli_command_the_agents_and_the_skill_name_exists(self) -> None:
        texts = [path.read_text(encoding="utf-8") for path in AGENTS.glob("*.agent.md")]
        texts.append((REPO / ".github" / "skills" / "harness-orchestration" / "SKILL.md").read_text(encoding="utf-8"))
        words: set = set()
        for text in texts:
            for span in re.findall(r"`([^`]+)`", text) + re.findall(r"cli\.py ([^\n`]+)", text):
                span = span.replace("python3 .harness/engine/cli.py ", "").replace(".harness/engine/cli.py ", "")
                parts = span.split()
                if parts and parts[0] in ("request", "handoff", "brief", "attempt") and len(parts) > 1 and re.match(r"^[a-z-]+$", parts[1]):
                    words.add(" ".join(parts[:2]))
                elif parts and parts[0] in ("dispatch", "promote", "check"):
                    words.add(parts[0])
        self.assertGreaterEqual(len(words), 8)
        for command in sorted(words):
            with self.subTest(command):
                completed = subprocess.run([sys.executable, str(CLI), *command.split(), "--help"], capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_the_bodies_and_the_skill_have_no_hard_coded_numbers(self) -> None:
        paths = list(AGENTS.glob("*.agent.md")) + [REPO / ".github" / "skills" / "harness-orchestration" / "SKILL.md"]
        for path in paths:
            if path.name == "verifier.agent.md":
                continue
            with self.subTest(path.name):
                found = re.findall(r"\d+\s*(?:轮|次|行|字节|条|个|秒|分钟)", path.read_text(encoding="utf-8"))
                self.assertEqual(found, [])

    def test_the_skill_follows_the_naming_rule_and_covers_the_whole_flow(self) -> None:
        skill = REPO / ".github" / "skills" / "harness-orchestration" / "SKILL.md"
        self.assertEqual(frontmatter(skill)["name"], "harness-orchestration")
        text = skill.read_text(encoding="utf-8")
        for needle in ("request new", "add-input", "brief set", "attempt new", "dispatch", "--dry-run", "approve-promote", "set-status", "--require-conclusion",
                       "--human-approved", "hitl", "你不能自己运行"):
            self.assertIn(needle, text)

    def test_the_roles_are_told_to_keep_the_last_reply_short_and_the_reviewer_to_read_the_diff(self) -> None:
        for name in ("builder", "reviewer"):
            text = (REPO / ".github" / "agents" / f"{name}.agent.md").read_text(encoding="utf-8")
            self.assertIn("## 最后一条回复", text, name)
            self.assertIn("已交接", text, name)
        self.assertIn("candidate.diff", (REPO / ".github" / "agents" / "reviewer.agent.md").read_text(encoding="utf-8"))
        skill = (REPO / ".github" / "skills" / "harness-orchestration" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("assignment_copied_from_builder", skill)
        self.assertIn("candidate.diff", skill)

    def test_there_is_no_l3_entry_skill(self) -> None:
        self.assertFalse((REPO / ".github" / "skills" / "l3").exists())  # L3 starts from the dropdown (B8 decision)


class ModelSeriesDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        copy_repo(self.root)

    def doctor(self) -> subprocess.CompletedProcess:
        import os

        return subprocess.run([sys.executable, str(CLI), "doctor"], text=True, encoding="utf-8", capture_output=True,
                              env={**os.environ, "HARNESS_ROOT": str(self.root)}, check=False)

    def set_model(self, agent: str, value: str) -> None:
        path = self.root / ".github" / "agents" / f"{agent}.agent.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(re.sub(r"^model:.*$", f"model: {value}", text, flags=re.MULTILINE), encoding="utf-8")

    def test_the_shipped_agents_pass(self) -> None:
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("模型系列检查完成", result.stdout)

    def test_reviewer_on_the_builders_series_is_an_error(self) -> None:
        self.set_model("reviewer", "['Claude Sonnet 5.5 (copilot)']")
        result = self.doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("builder 和 reviewer 用了同一系列", result.stdout.replace("agent ", "").replace("reviewer 和 builder", "builder 和 reviewer"))

    def test_a_fallback_list_that_crosses_series_is_an_error(self) -> None:
        self.set_model("builder", "['Claude Sonnet 5.5', 'Claude Opus 5.5']")
        result = self.doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("跨了系列", result.stdout)

    def test_an_unknown_model_name_is_a_warning_only(self) -> None:
        self.set_model("builder", "['Claude Sonnet 5.5', 'Some New Model']")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("不认识的模型名", result.stdout)

    def test_a_single_name_instead_of_a_list_works(self) -> None:
        self.set_model("builder", "Claude Sonnet 5.5")
        self.assertEqual(self.doctor().returncode, 0)
        self.set_model("reviewer", "Claude Haiku 4.5")
        self.assertEqual(self.doctor().returncode, 0)  # a different series from builder is all the rule asks

    def test_without_agents_json_nothing_is_checked(self) -> None:
        (self.root / ".harness" / "policies" / "agents.json").unlink()
        self.set_model("reviewer", "['Claude Sonnet 5.5']")
        result = self.doctor()
        self.assertNotIn("同一系列", result.stdout)


class CallLogTests(RequestCase):
    def test_start_and_stop_calls_log_where_the_transcript_is_and_the_model(self) -> None:
        self.hook(payload("SessionStart", "log-session", model="claude-opus-5.5", source="new"))
        self.hook(payload("SubagentStart", "log-session", agent_id="a1", agent_type="builder"))
        calls = {item["event"]: item for item in self.call_lines() if item.get("session_id") == "log-session"}
        self.assertEqual(calls["SessionStart"]["model"], "claude-opus-5.5")
        self.assertTrue(calls["SessionStart"]["transcript"].endswith("x.jsonl"))
        self.assertTrue(calls["SubagentStart"]["transcript"])
        self.assertNotIn("model", calls["SubagentStart"])


if __name__ == "__main__":
    unittest.main()
