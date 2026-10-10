"""Request module (B7, M4-1～M4-3): contracts, the request CLI, and promote. Whole lifecycles run in a temp root."""

from __future__ import annotations

import concurrent.futures
import io
import json
import os
import re
import stat
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from support import HarnessTestCase, payload, pre_tool

from core import schema
from modules.request import brief as brief_module
from modules.request import layout, planapproval, promote, store

SESSION = "sess-main"
BRIEF = "# 简报\n- 部署前要先停写 [来源: knowledge-base/deploy.md#停写]\n- 表名用小写 [来源: knowledge-base/naming.md#表]\n"
FILLED = "## 目标\n写 slugify。\n\n## 验收标准\n- slugify('A b') 返回 'a-b'\n"


def fill(text: str) -> str:
    """Replace the template's two placeholders with real content."""
    return text.replace("## 目标\n\n（待填）", "## 目标\n\n写 slugify。").replace("## 验收标准\n\n（待填）", "## 验收标准\n\n- slugify('A b') 返回 'a-b'")


class RequestCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.hook(payload("UserPromptSubmit", SESSION, prompt="start"))  # a real session has hook calls, so it has state

    # --- helpers ------------------------------------------------------------------------------

    def run_cli(self, *arguments: str, ok: bool = True) -> Dict[str, Any]:
        completed = self.cli(*arguments)
        if ok:
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            return json.loads(completed.stdout)
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        return {"stderr": completed.stderr, "stdout": completed.stdout}

    def refused(self, *arguments: str) -> str:
        return self.run_cli(*arguments, ok=False)["stderr"]

    def new_request(self, title: str = "Add slugify", session: str = SESSION) -> str:
        return self.run_cli("request", "new", "--title", title, "--session-id", session)["request_id"]

    def rd(self, request_id: str) -> Path:
        return self.root / ".workspace" / "sandbox" / "requests" / request_id

    def request(self, request_id: str) -> Dict[str, Any]:
        return json.loads((self.rd(request_id) / "request.json").read_text(encoding="utf-8"))

    def write(self, relative: str, text: str = "x\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))  # the text as written: Windows must not turn \n into \r\n
        return path

    def assignment(self, request_id: str, number: int, role: str) -> Path:
        return self.rd(request_id) / "handoffs" / "orchestrator" / f"attempt-{number:03d}" / f"to-{role}" / "assignment.md"

    def fill_assignment(self, request_id: str, number: int, role: str) -> None:
        path = self.assignment(request_id, number, role)
        path.write_text(fill(path.read_text(encoding="utf-8")), encoding="utf-8")

    def output(self, request_id: str, number: int, role: str, relative: str, text: str = "x\n") -> None:
        path = self.rd(request_id) / role / "outputs" / f"attempt-{number:03d}" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))  # the text as written: Windows must not turn \n into \r\n

    def plan_file(self, request_id: str) -> Path:
        return self.rd(request_id) / "orchestrator" / "plan.md"

    def write_plan(self, request_id: str, text: str = "# 计划\n\n写 slugify，再评审。\n") -> None:
        self.plan_file(request_id).write_text(text, encoding="utf-8")

    def approve_plan(self, request_id: str = "", code: Optional[str] = None, out: Any = None) -> Dict[str, Any]:
        """A person at a terminal approves plan.md (default: types the right code)."""
        typed = code if code is not None else (store.sha256_file(self.plan_file(request_id))[:8] if request_id else "")
        return planapproval.approve(self.root, request_id, reader=lambda _prompt: typed, interactive=True, out=out or io.StringIO())

    def ready_plan(self, request_id: str) -> None:
        """Write the plan when it is still the template, and approve it when it has no approval."""
        if "（待填）" in self.plan_file(request_id).read_text(encoding="utf-8"):
            self.write_plan(request_id)
        if not planapproval.approved(self.root, request_id, self.request(request_id)):
            self.approve_plan(request_id)

    def attempt(self, request_id: str, approved: Optional[str] = None) -> Dict[str, Any]:
        extra = ["--human-approved", approved] if approved else []
        self.ready_plan(request_id)
        return self.run_cli("attempt", "new", "--request", request_id, *extra)

    def dispatch(self, request_id: str, role: str, *inputs: str, ok: bool = True) -> Any:
        extra: List[str] = []
        for item in inputs:
            extra += ["--input", item]
        return self.run_cli("dispatch", "--request", request_id, "--role", role, *extra, ok=ok)

    def submit(self, request_id: str, role: str, status: str, *extra: str, summary: str = "done", ok: bool = True) -> Any:
        return self.run_cli("handoff", "submit", "--request", request_id, "--role", role, "--status", status, "--summary", summary, *extra, ok=ok)

    def builder_round(self, request_id: str, number: int, status: str = "passed", body: str = "def slugify(s):\n    return s\n") -> None:
        """Fill, dispatch builder, builder writes src/slug.py and hands off."""
        self.fill_assignment(request_id, number, "builder")
        self.dispatch(request_id, "builder")
        if status == "passed":
            self.output(request_id, number, "builder", "src/slug.py", body)
            self.submit(request_id, "builder", "passed", "--output", "src/slug.py")
        else:
            self.submit(request_id, "builder", status, "--blocker", "tests do not pass")

    def reviewer_round(self, request_id: str, number: int, status: str = "passed") -> None:
        self.fill_assignment(request_id, number, "reviewer")
        self.dispatch(request_id, "reviewer")
        if status == "passed":
            self.output(request_id, number, "reviewer", "evidence/test.log", "ok\n")
            self.submit(request_id, "reviewer", "passed", "--evidence", "evidence/test.log")
        else:
            self.output(request_id, number, "reviewer", "evidence/test.log", "1 failed\n")
            self.submit(request_id, "reviewer", status, "--evidence", "evidence/test.log", "--blocker", "slugify keeps spaces")

    def passed_request(self) -> str:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.reviewer_round(request_id, 1)
        return request_id

    def approve(self, request_id: str, code: Optional[str] = None) -> Dict[str, Any]:
        """A person at a terminal: stands in with a reader that types `code` (default: the right code)."""
        plan = self.request(request_id)["promote"].get("plan_sha256", "")
        return promote.approve(self.root, request_id, reader=lambda _prompt: code if code is not None else plan[:8], interactive=True, out=io.StringIO())

    def promote_for_real(self, request_id: str) -> Dict[str, Any]:
        self.run_cli("promote", "--request", request_id, "--dry-run")
        self.approve(request_id)
        return self.run_cli("promote", "--request", request_id)

    def check(self, request_id: str, *extra: str) -> Dict[str, Any]:
        completed = self.cli("check", "--request", request_id, *extra)
        return {**json.loads(completed.stdout), "exit": completed.returncode}


class SchemaExtensionTests(unittest.TestCase):
    def test_new_keys(self) -> None:
        spec = {"type": "object", "additionalProperties": False, "properties": {
            "a": {"type": "string", "minLength": 2, "maxLength": 3, "pattern": "^x"},
            "b": {"type": "array", "minItems": 1, "maxItems": 2}}}
        self.assertEqual(schema.validate({"a": "xy", "b": [1]}, spec), [])
        self.assertEqual(len(schema.validate({"a": "y"}, spec)), 2)  # too short, wrong pattern
        self.assertTrue(schema.validate({"a": "xyzw"}, spec))
        self.assertTrue(schema.validate({"b": []}, spec))
        self.assertTrue(schema.validate({"b": [1, 2, 3]}, spec))
        self.assertTrue(schema.validate({"c": 1}, spec))  # unexpected key


class ContractTests(RequestCase):
    def test_the_contracts_reject_missing_fields_and_wrong_enums(self) -> None:
        handoff = {"schema_version": 1, "request_id": "r", "attempt": 1, "role": "builder", "status": "passed", "summary": "s",
                   "outputs": [], "evidence": [], "blockers": [], "next": "", "kb_additions": [], "submitted_at": "t"}
        store.validate(self.root, "handoff", handoff, "handoff")
        for change in (
            lambda d: d.pop("status"), lambda d: d.update(status="done"), lambda d: d.update(role="orchestrator"),
            lambda d: d.update(summary=""), lambda d: d.update(attempt=0), lambda d: d.update(schema_version=2),
            lambda d: d.update(kb_additions=[{"source": "a"}]), lambda d: d.update(outputs=[""]),
        ):
            broken = json.loads(json.dumps(handoff))
            change(broken)
            with self.subTest(str(broken)[:60]), self.assertRaises(ValueError):
                store.validate(self.root, "handoff", broken, "handoff")

    def test_manifest_and_request_contracts(self) -> None:
        manifest = {"schema_version": 1, "request_id": "r", "attempt": 1, "role": "builder", "assignment": {"path": "assignment.md", "sha256": "x"},
                    "files": [{"path": "inputs/a", "source": "a", "purpose": "input", "sha256": "x"}], "brief": None, "brief_version": 0,
                    "brief_delta": [], "dispatched_at": "t"}
        store.validate(self.root, "manifest", manifest, "manifest")
        for change in (lambda d: d.pop("brief_delta"), lambda d: d["files"][0].update(purpose="other"), lambda d: d.update(role="x")):
            broken = json.loads(json.dumps(manifest))
            change(broken)
            with self.assertRaises(ValueError):
                store.validate(self.root, "manifest", broken, "manifest")
        request_id = self.new_request()
        data = self.request(request_id)
        store.validate(self.root, "request", data, "request")
        data["status"] = "done"
        with self.assertRaises(ValueError):
            store.validate(self.root, "request", data, "request")


class NewRequestTests(RequestCase):
    def test_new_builds_the_folder_and_puts_the_session_into_l3(self) -> None:
        request_id = self.new_request("Add slugify")
        self.assertRegex(request_id, r"^\d{8}-\d{4}-add-slugify-[a-z0-9]{4}$")
        directory = self.rd(request_id)
        for sub in ("orchestrator/plan.md", "builder/.pending", "builder/outputs", "reviewer/outputs",
                    "handoffs/orchestrator/init-inputs", "handoffs/builder", "handoffs/reviewer", "request.json"):
            self.assertTrue((directory / sub).exists(), sub)
        data = self.request(request_id)
        self.assertEqual((data["status"], data["attempt"], data["session_id"]), ("open", 0, SESSION))
        state = self.session_state(SESSION)
        self.assertEqual(state["active_request"], request_id)
        self.assertEqual(self.session_effective_level(SESSION), 3)

    def session_effective_level(self, session: str) -> int:
        state = json.loads(self.state_file(session).read_text(encoding="utf-8"))
        return 3 if state["active_request"] else state["level"]

    def test_a_title_with_no_ascii_gets_a_plain_slug(self) -> None:
        request_id = self.new_request("写一个函数")
        self.assertRegex(request_id, r"^\d{8}-\d{4}-task-[a-z0-9]{4}$")

    def test_an_unknown_session_is_refused_and_nothing_is_created(self) -> None:
        message = self.refused("request", "new", "--title", "x", "--session-id", "typo-session")
        self.assertIn("没有会话", message)
        self.assertFalse((self.root / ".workspace").exists())

    def test_one_open_request_per_session(self) -> None:
        first = self.new_request()
        message = self.refused("request", "new", "--title", "second", "--session-id", SESSION)
        self.assertIn(first, message)
        self.assertEqual(len(list((self.root / ".workspace" / "sandbox" / "requests").iterdir())), 1)

    def test_an_empty_title_is_refused(self) -> None:
        self.assertIn("title", self.refused("request", "new", "--title", "  ", "--session-id", SESSION))

    def test_level_set_is_refused_during_a_request(self) -> None:
        self.new_request()
        self.assertNotEqual(self.cli("level", "set", "--session-id", SESSION, "--level", "2", "--reason", "x").returncode, 0)

    def test_show_prints_request_json(self) -> None:
        request_id = self.new_request()
        self.assertEqual(self.run_cli("request", "show", "--request", request_id)["request_id"], request_id)

    def test_an_unknown_or_unsafe_request_id(self) -> None:
        self.assertIn("没有请求", self.refused("request", "show", "--request", "nope"))
        self.assertIn("不合法", self.refused("request", "show", "--request", "../x"))


class InputAndBriefTests(RequestCase):
    def test_add_input_copies_files_and_folders_with_their_repo_paths(self) -> None:
        request_id = self.new_request()
        self.write("docs/spec.md", "spec\n")
        self.write("src/a.py", "a\n")
        self.write("src/b.py", "b\n")
        self.write("src/__pycache__/c.pyc", "skip\n")
        result = self.run_cli("request", "add-input", "--request", request_id, "docs/spec.md", "src")
        base = self.rd(request_id) / "handoffs" / "orchestrator" / "init-inputs"
        self.assertEqual(sorted(result["added"]), ["docs/spec.md", "src/a.py", "src/b.py"])
        self.assertEqual((base / "src" / "a.py").read_text(encoding="utf-8"), "a\n")
        self.assertFalse((base / "src" / "__pycache__").exists())
        self.assertEqual(len(self.request(request_id)["inputs"]), 3)

    def test_add_input_refuses_outside_missing_and_too_many(self) -> None:
        request_id = self.new_request()
        outside = self.root.parent / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        self.addCleanup(outside.unlink)
        self.assertIn("仓库之外", self.refused("request", "add-input", "--request", request_id, str(outside)))
        self.assertIn("不存在", self.refused("request", "add-input", "--request", request_id, "nope.txt"))
        policy = self.root / ".harness" / "policies" / "orchestration.json"
        data = json.loads(policy.read_text(encoding="utf-8"))
        data["inputs"]["max_files"] = 1
        policy.write_text(json.dumps(data), encoding="utf-8")
        self.write("many/a.txt")
        self.write("many/b.txt")
        self.assertIn("上限", self.refused("request", "add-input", "--request", request_id, "many"))

    def test_add_input_is_closed_after_the_first_dispatch(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.dispatch(request_id, "builder")
        self.write("docs/late.md")
        self.assertIn("dispatch 时用 --input", self.refused("request", "add-input", "--request", request_id, "docs/late.md"))

    def draft(self, request_id: str, text: str) -> str:
        path = self.rd(request_id) / "orchestrator" / "brief-draft.md"
        path.write_text(text, encoding="utf-8")
        return path.relative_to(self.root).as_posix()

    def test_brief_set_stores_a_version_and_a_snapshot(self) -> None:
        request_id = self.new_request()
        result = self.run_cli("brief", "set", "--request", request_id, self.draft(request_id, BRIEF))
        self.assertEqual((result["brief_version"], result["entries"], result["changed"]), (1, 2, True))
        base = self.rd(request_id) / "handoffs" / "orchestrator" / "init-inputs"
        self.assertEqual((base / "knowledge-brief.md").read_text(encoding="utf-8"), BRIEF)
        self.assertTrue((base / "brief-history" / "v001.md").exists())
        self.assertEqual(self.request(request_id)["brief"]["version"], 1)

    def test_the_same_brief_again_is_not_a_new_version(self) -> None:
        request_id = self.new_request()
        draft = self.draft(request_id, BRIEF)
        self.run_cli("brief", "set", "--request", request_id, draft)
        again = self.run_cli("brief", "set", "--request", request_id, draft)
        self.assertEqual((again["brief_version"], again["changed"]), (1, False))

    def test_a_new_text_is_the_next_version_and_the_old_snapshot_stays(self) -> None:
        request_id = self.new_request()
        self.run_cli("brief", "set", "--request", request_id, self.draft(request_id, BRIEF))
        result = self.run_cli("brief", "set", "--request", request_id, self.draft(request_id, BRIEF + "- 新结论 [来源: a.md#b]\n"))
        self.assertEqual(result["brief_version"], 2)
        base = self.rd(request_id) / "handoffs" / "orchestrator" / "init-inputs" / "brief-history"
        self.assertEqual((base / "v001.md").read_text(encoding="utf-8"), BRIEF)

    def test_bad_briefs_are_refused(self) -> None:
        request_id = self.new_request()
        cases = {
            "no source": "- 只有结论\n",
            "empty source": "- 结论 [来源: ]\n",
            "prose line": "这是一段话\n- 结论 [来源: a.md#b]\n",
            "no entries": "# 只有标题\n",
            "empty": "",
            "source first": "- [来源: a.md#b] 结论\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                message = self.refused("brief", "set", "--request", request_id, self.draft(request_id, text))
                self.assertIn("来源", message)
        self.assertEqual(self.request(request_id)["brief"]["version"], 0)

    def test_a_brief_that_is_too_big_or_has_too_many_entries_is_refused(self) -> None:
        request_id = self.new_request()
        policy = self.root / ".harness" / "policies" / "orchestration.json"
        data = json.loads(policy.read_text(encoding="utf-8"))
        data["brief"] = {"max_bytes": 120, "max_entries": 2}
        policy.write_text(json.dumps(data), encoding="utf-8")
        big = "".join(f"- 结论 {n} [来源: a.md#{n}]\n" for n in range(2)) + "x" * 100
        self.assertIn("太大", self.refused("brief", "set", "--request", request_id, self.draft(request_id, big)))
        many = "".join(f"- c{n} [来源: a#{n}]\n" for n in range(3))
        self.assertIn("条目太多", self.refused("brief", "set", "--request", request_id, self.draft(request_id, many)))

    def test_the_delta_is_what_is_new_or_changed(self) -> None:
        old = BRIEF
        new = BRIEF.replace("小写", "小写加下划线") + "- 新 [来源: x.md#y]\n"
        self.assertEqual(brief_module.delta(old, new), ["- 表名用小写加下划线 [来源: knowledge-base/naming.md#表]", "- 新 [来源: x.md#y]"])
        self.assertEqual(brief_module.delta(BRIEF, BRIEF), [])


class AttemptTests(RequestCase):
    def test_attempt_new_builds_both_packages_with_the_template(self) -> None:
        request_id = self.new_request()
        result = self.attempt(request_id)
        self.assertEqual(result["attempt"], 1)
        text = self.assignment(request_id, 1, "builder").read_text(encoding="utf-8")
        self.assertIn("## 验收标准", text)
        self.assertIn("先读", text)
        self.assertIn("kb-addition", text)
        self.assertIn(f".workspace/sandbox/requests/{request_id}/builder/outputs/attempt-001", text)
        self.assertTrue((self.rd(request_id) / "reviewer" / "outputs" / "attempt-001").is_dir())
        self.assertTrue((self.rd(request_id) / "handoffs" / "orchestrator" / "attempt-001" / "to-reviewer" / "candidate").is_dir())
        self.assertEqual(self.request(request_id)["attempt"], 1)

    def test_the_second_attempt_needs_a_handoff_from_the_first(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        message = self.refused("attempt", "new", "--request", request_id)
        self.assertIn("还没有任何 handoff", message)

    def test_past_the_limit_the_person_must_approve(self) -> None:
        request_id = self.new_request()
        for number in (1, 2):
            self.attempt(request_id)
            self.builder_round(request_id, number, status="blocked")
        message = self.refused("attempt", "new", "--request", request_id)
        self.assertIn("上限", message)
        self.assertIn("--human-approved", message)
        self.assertIn("不要自己重置计数", message)
        self.assertIn("上限", self.refused("attempt", "new", "--request", request_id, "--human-approved", "  "))
        self.assertEqual(self.attempt(request_id, approved="用户在对话里同意再试一轮")["attempt"], 3)
        self.assertEqual(self.request(request_id)["attempts"][2]["human_approved"], "用户在对话里同意再试一轮")

    def test_a_request_with_a_conclusion_takes_no_more_attempts(self) -> None:
        request_id = self.new_request()
        self.run_cli("request", "set-status", "--request", request_id, "--status", "abandoned", "--reason", "no")
        self.assertIn("已经结束", self.refused("attempt", "new", "--request", request_id))


class PlanApprovalTests(RequestCase):
    """M7-1: a person approves orchestrator/plan.md before the first attempt."""

    def test_no_attempt_while_the_plan_is_the_template(self) -> None:
        request_id = self.new_request()
        message = self.refused("attempt", "new", "--request", request_id)
        self.assertIn("计划还没写完", message)
        self.assertEqual(self.request(request_id)["attempt"], 0)

    def test_no_attempt_before_the_person_approves_and_the_refusal_says_what_to_do(self) -> None:
        request_id = self.new_request()
        self.write_plan(request_id)
        message = self.refused("attempt", "new", "--request", request_id)
        self.assertIn("还没有经用户批准", message)
        self.assertIn(f"[plan.md](.workspace/sandbox/requests/{request_id}/orchestrator/plan.md)", message)
        self.assertIn("request approve-plan", message)
        self.assertIn("request wait", message)
        self.assertEqual(self.request(request_id)["attempt"], 0)

    def test_the_approval_is_bound_to_the_plan_and_the_screen_names_the_file(self) -> None:
        request_id = self.new_request()
        self.write_plan(request_id)
        screen = io.StringIO()
        with self.assertRaises(layout.CommandError):
            self.approve_plan(request_id, code="nope", out=screen)
        self.assertNotIn("plan", self.request(request_id))
        result = self.approve_plan(request_id, out=screen)
        self.assertTrue(result["approved"])
        self.assertIn(f".workspace/sandbox/requests/{request_id}/orchestrator/plan.md", screen.getvalue())
        self.assertNotIn("写 slugify，再评审", screen.getvalue())  # the plan is read in the editor, not in the terminal
        self.assertEqual(self.request(request_id)["plan"]["approved_sha256"], store.sha256_file(self.plan_file(request_id)))
        self.assertEqual(self.run_cli("attempt", "new", "--request", request_id)["attempt"], 1)

    def test_a_changed_plan_needs_a_new_approval_and_an_unchanged_one_does_not(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1, status="blocked")
        self.assertEqual(self.run_cli("attempt", "new", "--request", request_id)["attempt"], 2)  # same plan: no new approval
        self.builder_round(request_id, 2, status="blocked")
        self.write_plan(request_id, "# 计划\n\n换一个做法。\n")
        message = self.refused("attempt", "new", "--request", request_id, "--human-approved", "用户同意")
        self.assertIn("计划在批准之后改过", message)
        self.approve_plan(request_id)
        self.assertEqual(self.run_cli("attempt", "new", "--request", request_id, "--human-approved", "用户同意")["attempt"], 3)

    def test_only_a_person_at_a_terminal_can_approve(self) -> None:
        request_id = self.new_request()
        self.write_plan(request_id)
        self.assertIn("只能由用户在自己的终端里手动运行", self.refused("request", "approve-plan", "--request", request_id))
        with self.assertRaises(layout.CommandError):
            planapproval.approve(self.root, request_id, reader=lambda _p: "x", interactive=False, out=io.StringIO())
        for command in (f"python3 .harness/engine/cli.py request approve-plan --request {request_id}", "harness request approve-plan", "harness task approve-plan", "harness task approve-promote"):
            denied = self.hook(pre_tool(SESSION, "run_in_terminal", {"command": command}))
            self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny", command)

    def test_without_an_id_the_one_request_waiting_for_its_plan_is_used(self) -> None:
        with self.assertRaises(layout.CommandError):
            self.approve_plan()  # nothing waits
        request_id = self.new_request()
        with self.assertRaises(layout.CommandError):
            self.approve_plan()  # the plan is still the template
        self.write_plan(request_id)
        code = store.sha256_file(self.plan_file(request_id))[:8]
        self.assertEqual(self.approve_plan(code=code)["request_id"], request_id)
        listed = self.run_cli("request", "list")["requests"][0]
        self.assertTrue(listed["plan_ready"] and listed["plan_approved"])


class DispatchTests(RequestCase):
    def test_an_unfilled_assignment_is_refused(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.assertIn("待填", self.refused("dispatch", "--request", request_id, "--role", "builder"))
        path = self.assignment(request_id, 1, "builder")
        path.write_text("## 目标\n写。\n\n## 验收标准\n\n## 先读什么\n1. x\n", encoding="utf-8")
        self.assertIn("验收标准", self.refused("dispatch", "--request", request_id, "--role", "builder"))

    def test_dispatch_needs_an_attempt(self) -> None:
        request_id = self.new_request()
        self.assertIn("attempt new", self.refused("dispatch", "--request", request_id, "--role", "builder"))

    def test_the_builder_package_is_complete_valid_and_read_only(self) -> None:
        request_id = self.new_request()
        self.write("docs/spec.md", "spec\n")
        self.run_cli("brief", "set", "--request", request_id, self.write(f".workspace/sandbox/requests/{request_id}/orchestrator/b.md", BRIEF).relative_to(self.root).as_posix())
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        result = self.dispatch(request_id, "builder", "docs/spec.md")
        package = self.assignment(request_id, 1, "builder").parent
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        store.validate(self.root, "manifest", manifest, "manifest")
        self.assertEqual((manifest["role"], manifest["attempt"], manifest["brief_version"], manifest["brief_delta"]), ("builder", 1, 1, []))
        self.assertTrue(manifest["brief"].endswith("init-inputs/knowledge-brief.md"))
        self.assertEqual([f["purpose"] for f in manifest["files"]], ["input"])
        self.assertEqual((package / manifest["files"][0]["path"]).read_text(encoding="utf-8"), "spec\n")
        for name in ("assignment.md", "manifest.json", manifest["files"][0]["path"]):
            self.assertFalse(os.stat(package / name).st_mode & stat.S_IWUSR, name)
        self.assertEqual(result["files"], 1)
        data = self.request(request_id)
        self.assertEqual(data["attempts"][0]["dispatched"]["builder"]["brief_version"], 1)
        self.assertEqual(data["pending_dispatch"][0]["role"], "builder")

    def test_the_same_role_cannot_be_dispatched_twice(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.dispatch(request_id, "builder")
        self.assertIn("已经派发过", self.refused("dispatch", "--request", request_id, "--role", "builder"))

    def test_the_reviewer_needs_a_passed_builder_handoff(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "reviewer")
        self.assertIn("还没有 handoff", self.refused("dispatch", "--request", request_id, "--role", "reviewer"))
        self.builder_round(request_id, 1, status="blocked")
        self.assertIn("blocked", self.refused("dispatch", "--request", request_id, "--role", "reviewer"))

    def test_the_reviewer_package_holds_the_builders_outputs_as_candidates(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.output(request_id, 1, "builder", "src/private-notes.txt", "secret\n")  # not listed in the handoff
        self.fill_assignment(request_id, 1, "reviewer")
        self.dispatch(request_id, "reviewer")
        package = self.assignment(request_id, 1, "reviewer").parent
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([(f["path"], f["purpose"]) for f in manifest["files"]], [("candidate/src/slug.py", "candidate")])
        self.assertFalse((package / "candidate" / "src" / "private-notes.txt").exists())

    def test_an_input_outside_the_repo_leaves_no_half_built_package(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.write("docs/a.md")
        message = self.refused("dispatch", "--request", request_id, "--role", "builder", "--input", "docs/a.md", "--input", "/etc/hosts")
        self.assertIn("仓库之外", message)
        package = self.assignment(request_id, 1, "builder").parent
        self.assertEqual(list((package / "inputs").iterdir()), [])
        self.assertFalse((package / "manifest.json").exists())
        self.dispatch(request_id, "builder", "docs/a.md")  # and it can still be dispatched

    def test_attempt_two_carries_a_brief_delta_and_the_previous_evidence(self) -> None:
        request_id = self.new_request()
        draft = f".workspace/sandbox/requests/{request_id}/orchestrator/b.md"
        self.write(draft, BRIEF)
        self.run_cli("brief", "set", "--request", request_id, draft)
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.reviewer_round(request_id, 1, status="failed")
        self.write(draft, BRIEF + "- 新增的结论 [来源: knowledge-base/x.md#y]\n")
        self.run_cli("brief", "set", "--request", request_id, draft)
        self.attempt(request_id)
        self.fill_assignment(request_id, 2, "builder")
        self.dispatch(request_id, "builder")
        package = self.assignment(request_id, 2, "builder").parent
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["brief_version"], 2)
        self.assertEqual(manifest["brief_delta"], ["- 新增的结论 [来源: knowledge-base/x.md#y]"])
        paths = sorted(f["path"] for f in manifest["files"])
        self.assertEqual(paths, ["inputs/previous-attempt/builder-handoff.json", "inputs/previous-attempt/reviewer-evidence/evidence/test.log",
                                 "inputs/previous-attempt/reviewer-handoff.json"])
        self.assertTrue(all(f["purpose"] == "previous-attempt" for f in manifest["files"]))

    def test_the_first_dispatch_has_no_delta_and_an_unchanged_brief_has_none(self) -> None:
        request_id = self.new_request()
        draft = f".workspace/sandbox/requests/{request_id}/orchestrator/b.md"
        self.write(draft, BRIEF)
        self.run_cli("brief", "set", "--request", request_id, draft)
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.reviewer_round(request_id, 1, status="failed")
        self.attempt(request_id)
        self.fill_assignment(request_id, 2, "builder")
        self.dispatch(request_id, "builder")
        package = self.assignment(request_id, 2, "builder").parent
        self.assertEqual(json.loads((package / "manifest.json").read_text(encoding="utf-8"))["brief_delta"], [])

    def test_no_brief_means_none_in_the_manifest(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.dispatch(request_id, "builder")
        manifest = json.loads((self.assignment(request_id, 1, "builder").parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["brief"], manifest["brief_version"]), (None, 0))


class HandoffTests(RequestCase):
    def ready(self) -> str:
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.dispatch(request_id, "builder")
        return request_id

    def test_submit_writes_a_valid_read_only_handoff(self) -> None:
        request_id = self.ready()
        self.output(request_id, 1, "builder", "src/slug.py")
        self.output(request_id, 1, "builder", "notes/self-test.log", "ok\n")
        result = self.submit(
            request_id, "builder", "passed", "--output", "src/slug.py", "--evidence", "notes/self-test.log", "--next", "review it",
            "--kb-addition", "knowledge-base/a.md#部署 :: 先停写再迁移", summary="line one\nline two")
        path = self.rd(request_id) / "handoffs" / "builder" / "attempt-001" / "handoff.json"
        handoff = json.loads(path.read_text(encoding="utf-8"))
        store.validate(self.root, "handoff", handoff, "handoff")
        self.assertEqual((handoff["status"], handoff["outputs"], handoff["evidence"], handoff["next"]), ("passed", ["src/slug.py"], ["notes/self-test.log"], "review it"))
        self.assertEqual(handoff["kb_additions"], [{"source": "knowledge-base/a.md#部署", "note": "先停写再迁移"}])
        self.assertEqual(result["kb_additions"], 1)
        self.assertFalse(os.stat(path).st_mode & stat.S_IWUSR)
        self.assertEqual(self.request(request_id)["attempts"][0]["handoffs"], {"builder": "passed"})

    def test_it_needs_a_dispatch_first(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.assertIn("还没有被派发", self.submit(request_id, "builder", "blocked", "--blocker", "x", ok=False)["stderr"])

    def test_one_handoff_per_role_and_attempt(self) -> None:
        request_id = self.ready()
        self.submit(request_id, "builder", "blocked", "--blocker", "x")
        self.assertIn("已经交接过", self.submit(request_id, "builder", "blocked", "--blocker", "y", ok=False)["stderr"])

    def test_every_refusal(self) -> None:
        request_id = self.ready()
        self.output(request_id, 1, "builder", "src/slug.py")
        cases = [
            (("passed",), {"summary": "  "}, "summary"),
            (("passed", "--output", "src/slug.py"), {"summary": "1\n2\n3\n4\n5\n6"}, "上限"),
            (("failed",), {}, "--blocker"),
            (("blocked",), {}, "--blocker"),
            (("passed",), {}, "--output"),
            (("passed", "--output", "src/none.py"), {}, "不是文件"),
            (("passed", "--output", "../escape.py"), {}, "之外"),
            (("passed", "--output", "/etc/hosts"), {}, "相对路径"),
            (("passed", "--output", "src"), {}, "不是文件"),
            (("passed", "--output", "src/slug.py", "--kb-addition", "no separator"), {}, "来源 :: 一句话结论"),
            (("passed", "--output", "src/slug.py", "--kb-addition", " :: note"), {}, "来源 :: 一句话结论"),
        ]
        for extra, options, expected in cases:
            with self.subTest(extra):
                result = self.submit(request_id, "builder", extra[0], *extra[1:], summary=options.get("summary", "done"), ok=False)
                self.assertIn(expected, result["stderr"])
        self.assertNotEqual(self.cli("handoff", "submit", "--request", request_id, "--role", "builder", "--status", "done", "--summary", "x").returncode, 0)
        self.assertEqual(self.request(request_id)["attempts"][0]["handoffs"], {})

    def test_a_reviewer_pass_needs_evidence(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.fill_assignment(request_id, 1, "reviewer")
        self.dispatch(request_id, "reviewer")
        self.assertIn("--evidence", self.submit(request_id, "reviewer", "passed", ok=False)["stderr"])


class ListTests(RequestCase):
    def test_list_shows_requests_newest_first_and_filters_by_status(self) -> None:
        first = self.new_request("first")
        self.run_cli("request", "set-status", "--request", first, "--status", "abandoned", "--reason", "x")
        second = self.new_request("second")
        listed = self.run_cli("request", "list")["requests"]
        self.assertEqual({r["request_id"] for r in listed}, {first, second})
        self.assertEqual([r["request_id"] for r in self.run_cli("request", "list", "--status", "open")["requests"]], [second])
        self.assertEqual(listed[0]["title"] in ("first", "second"), True)
        self.assertEqual(set(listed[0]), {"request_id", "title", "status", "attempt", "promote", "waiting_for_approval", "waiting_for", "created_at", "plan_ready", "plan_approved"})

    def test_list_with_no_requests_and_with_a_stray_folder(self) -> None:
        self.assertEqual(self.run_cli("request", "list")["requests"], [])
        (self.root / ".workspace" / "sandbox" / "requests" / "not-a-request").mkdir(parents=True)
        self.assertEqual(self.run_cli("request", "list")["requests"], [])


class StatusTests(RequestCase):
    def test_accepted_needs_a_passed_review_or_a_reason(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.assertIn("reviewer", self.refused("request", "set-status", "--request", request_id, "--status", "accepted"))
        self.reviewer_round(request_id, 1)
        result = self.run_cli("request", "set-status", "--request", request_id, "--status", "accepted", "--reason", "不回写，只看评审结论")
        self.assertTrue(result["session_released"])

    def test_accepted_needs_the_promote_when_the_reviewed_files_are_not_in_the_repository_yet(self) -> None:
        request_id = self.passed_request()
        message = self.refused("request", "set-status", "--request", request_id, "--status", "accepted")
        self.assertIn("promote", message)
        self.promote_for_real(request_id)
        self.assertTrue(self.run_cli("request", "set-status", "--request", request_id, "--status", "accepted")["session_released"])

    def test_accepted_without_a_review_is_possible_with_a_reason(self) -> None:
        request_id = self.new_request()
        self.run_cli("request", "set-status", "--request", request_id, "--status", "accepted", "--reason", "plan.md 记录：这个任务没有可评审的成果")
        self.assertTrue(self.request(request_id)["status_reason"].startswith("plan.md 记录"))

    def test_hitl_and_abandoned_need_a_reason(self) -> None:
        request_id = self.new_request()
        for status in ("hitl", "abandoned"):
            self.assertIn("--reason", self.refused("request", "set-status", "--request", request_id, "--status", status))
        self.assertNotEqual(self.cli("request", "set-status", "--request", request_id, "--status", "open").returncode, 0)

    def test_ending_a_request_returns_the_session_to_l1(self) -> None:
        request_id = self.new_request()
        self.run_cli("request", "set-status", "--request", request_id, "--status", "hitl", "--reason", "第二轮仍失败")
        self.assertIsNone(self.session_state(SESSION)["active_request"])
        self.assertEqual(self.session_state(SESSION)["level"], 1)
        self.new_request("again")  # the session can start another one

    def test_a_concluded_request_refuses_every_change(self) -> None:
        request_id = self.new_request()
        self.run_cli("request", "set-status", "--request", request_id, "--status", "abandoned", "--reason", "x")
        self.write("docs/a.md")
        for command in (
            ("request", "add-input", "--request", request_id, "docs/a.md"),
            ("request", "set-status", "--request", request_id, "--status", "hitl", "--reason", "y"),
            ("dispatch", "--request", request_id, "--role", "builder"),
            ("promote", "--request", request_id, "--dry-run"),
        ):
            with self.subTest(command):
                self.assertIn("已经结束", self.refused(*command))

    def test_ending_a_request_does_not_touch_a_session_that_moved_on(self) -> None:
        first = self.new_request()
        state = json.loads(self.state_file(SESSION).read_text(encoding="utf-8"))
        state["active_request"] = "some-other-request"
        self.state_file(SESSION).write_text(json.dumps(state), encoding="utf-8")
        result = self.run_cli("request", "set-status", "--request", first, "--status", "abandoned", "--reason", "x")
        self.assertFalse(result["session_released"])
        self.assertEqual(self.session_state(SESSION)["active_request"], "some-other-request")


class CheckTests(RequestCase):
    def test_a_fresh_request_and_a_full_one_pass(self) -> None:
        request_id = self.new_request()
        self.assertEqual(self.check(request_id)["problems"], [])
        self.run_cli("request", "set-status", "--request", request_id, "--status", "abandoned", "--reason", "x")
        done = self.passed_request()
        result = self.check(done)
        self.assertEqual((result["problems"], result["exit"], result["concluded"]), ([], 0, False))

    def test_require_conclusion(self) -> None:
        request_id = self.passed_request()
        result = self.check(request_id, "--require-conclusion")
        self.assertEqual(result["exit"], 1)
        self.assertIn("没有结论", result["problems"][0])
        self.promote_for_real(request_id)
        self.run_cli("request", "set-status", "--request", request_id, "--status", "accepted")
        result = self.check(request_id, "--require-conclusion")
        self.assertEqual((result["exit"], result["concluded"], result["problems"]), (0, True, []))

    def tamper(self, path: Path, text: str) -> None:
        os.chmod(path, 0o644)
        path.write_text(text, encoding="utf-8")

    def test_check_finds_each_kind_of_tampering(self) -> None:
        request_id = self.passed_request()
        directory = self.rd(request_id)
        builder = directory / "handoffs" / "orchestrator" / "attempt-001" / "to-builder"
        self.tamper(builder / "assignment.md", "changed")
        self.assertTrue(any("assignment.md 在派发之后被改动" in p for p in self.check(request_id)["problems"]))
        reviewer = directory / "handoffs" / "orchestrator" / "attempt-001" / "to-reviewer"
        self.tamper(reviewer / "candidate" / "src" / "slug.py", "evil")
        self.assertTrue(any("在派发之后被改动" in p and "candidate" in p for p in self.check(request_id)["problems"]))
        handoff = directory / "handoffs" / "builder" / "attempt-001" / "handoff.json"
        data = json.loads(handoff.read_text(encoding="utf-8"))
        data["status"] = "failed"
        self.tamper(handoff, json.dumps(data))
        problems = self.check(request_id)["problems"]
        self.assertTrue(any("request.json 记录的是 passed" in p for p in problems))
        self.assertTrue(any("没有 blockers" in p for p in problems))

    def test_check_finds_a_missing_manifest_a_missing_handoff_and_a_missing_folder(self) -> None:
        request_id = self.passed_request()
        directory = self.rd(request_id)
        os.chmod(directory / "handoffs" / "orchestrator" / "attempt-001" / "to-builder" / "manifest.json", 0o644)
        (directory / "handoffs" / "orchestrator" / "attempt-001" / "to-builder" / "manifest.json").unlink()
        os.chmod(directory / "handoffs" / "reviewer" / "attempt-001" / "handoff.json", 0o644)
        (directory / "handoffs" / "reviewer" / "attempt-001" / "handoff.json").unlink()
        (directory / "builder" / "outputs" / "attempt-001" / "src" / "slug.py").unlink()
        import shutil

        shutil.rmtree(str(directory / "reviewer" / "outputs"))
        problems = " | ".join(self.check(request_id)["problems"])
        for expected in ("缺 manifest.json", "reviewer 第 1 轮的 handoff，但文件不存在", "src/slug.py 不存在", "缺目录：reviewer/outputs"):
            self.assertIn(expected, problems)

    def test_check_finds_a_brief_edited_by_hand(self) -> None:
        request_id = self.new_request()
        draft = f".workspace/sandbox/requests/{request_id}/orchestrator/b.md"
        self.write(draft, BRIEF)
        self.run_cli("brief", "set", "--request", request_id, draft)
        live = self.rd(request_id) / "handoffs" / "orchestrator" / "init-inputs" / "knowledge-brief.md"
        live.write_text("- 偷偷改的 [来源: x#y]\n", encoding="utf-8")
        self.assertTrue(any("被直接改过" in p for p in self.check(request_id)["problems"]))

    def test_check_on_a_broken_request_json(self) -> None:
        request_id = self.new_request()
        path = self.rd(request_id) / "request.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = "weird"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = self.check(request_id)
        self.assertEqual(result["exit"], 1)
        self.assertIn("request.json", result["problems"][0])


class PromoteTests(RequestCase):
    def test_not_before_a_passed_review(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.assertIn("还不是 passed", self.refused("promote", "--request", request_id, "--dry-run"))
        self.reviewer_round(request_id, 1, status="failed")
        self.assertIn("还不是 passed", self.refused("promote", "--request", request_id, "--dry-run"))

    def test_dry_run_lists_files_and_changes_nothing(self) -> None:
        request_id = self.new_request()
        self.write("src/slug.py", "def slugify(s):\n    return s.lower()\n")
        self.attempt(request_id)
        self.builder_round(request_id, 1, body="def slugify(s):\n    return s.lower().replace(' ', '-')\n")
        self.reviewer_round(request_id, 1)
        result = self.run_cli("promote", "--request", request_id, "--dry-run")
        self.assertTrue(result["dry_run"])
        entry = result["files"][0]
        self.assertEqual((entry["path"], entry["action"], entry["added"], entry["removed"]), ("src/slug.py", "modify", 1, 1))
        self.assertNotIn("diff", entry)  # the agent gets the counts; the person sees the diff on the approval screen
        plan = promote.make_plan(self.root, request_id, self.request(request_id))
        self.assertTrue(any(line.startswith("+    return s.lower().replace") for line in plan["files"][0]["diff"]))
        self.assertEqual((self.root / "src" / "slug.py").read_text(encoding="utf-8"), "def slugify(s):\n    return s.lower()\n")
        self.assertEqual(self.request(request_id)["promote"]["state"], "dry_run")

    def test_the_approval_screen_names_the_review_file_and_the_file_holds_the_diff(self) -> None:
        request_id = self.new_request()
        self.write("src/slug.py", "def slugify(s):\n    return s.lower()\n")
        self.attempt(request_id)
        self.builder_round(request_id, 1, body="def slugify(s):\n    return s.lower().replace(' ', '-')\n")
        self.reviewer_round(request_id, 1)
        self.run_cli("promote", "--request", request_id, "--dry-run")
        out = io.StringIO()
        plan = self.request(request_id)["promote"]["plan_sha256"]
        dry = self.run_cli("promote", "--request", request_id, "--dry-run")
        review = self.rd(request_id) / "promote-plan.diff"
        self.assertEqual(dry["review_file"], f".workspace/sandbox/requests/{request_id}/promote-plan.diff")
        self.assertIn("promote-plan.diff", dry["next"])
        review.write_text("tampered\n", encoding="utf-8")  # the approval writes it again: the person approves the real plan
        promote.approve(self.root, request_id, reader=lambda _p: plan[:8], interactive=True, out=out)
        self.assertNotIn("+    return s.lower().replace", out.getvalue())  # the terminal stays short
        self.assertIn(dry["review_file"], out.getvalue())
        self.assertIn("modify    src/slug.py  (+1 -1)", out.getvalue())
        text = review.read_text(encoding="utf-8")
        self.assertIn("+    return s.lower().replace(' ', '-')", text)
        self.assertIn("-    return s.lower()", text)
        denied = self.hook(pre_tool(SESSION, "create_file", {"filePath": str(review), "content": "x"}))
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")  # only the CLI writes it

    def test_the_real_run_needs_a_matching_dry_run(self) -> None:
        request_id = self.passed_request()
        self.assertIn("--dry-run", self.refused("promote", "--request", request_id))
        self.run_cli("promote", "--request", request_id, "--dry-run")
        self.write("src/slug.py", "someone changed the repo\n")  # after the person looked at the plan
        self.assertIn("重新运行 --dry-run", self.refused("promote", "--request", request_id))
        self.assertEqual((self.root / "src" / "slug.py").read_text(encoding="utf-8"), "someone changed the repo\n")

    def test_promote_copies_the_reviewed_files_and_records_it(self) -> None:
        request_id = self.passed_request()
        result = self.promote_for_real(request_id)
        self.assertFalse(result["dry_run"])
        self.assertEqual((self.root / "src" / "slug.py").read_text(encoding="utf-8"), "def slugify(s):\n    return s\n")
        record = self.request(request_id)["promote"]
        self.assertEqual((record["state"], [f["path"] for f in record["files"]], record["files"][0]["action"]), ("done", ["src/slug.py"], "create"))
        self.assertIn("已经 promote 过", self.refused("promote", "--request", request_id))
        self.assertIn("已经 promote 过", self.refused("promote", "--request", request_id, "--dry-run"))
        self.run_cli("request", "set-status", "--request", request_id, "--status", "accepted")
        self.assertEqual(self.check(request_id, "--require-conclusion")["problems"], [])

    def test_an_unchanged_file_is_listed_and_not_rewritten(self) -> None:
        request_id = self.new_request()
        self.write("src/slug.py", "def slugify(s):\n    return s\n")
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.reviewer_round(request_id, 1)
        plan = self.run_cli("promote", "--request", request_id, "--dry-run")
        self.assertEqual(plan["files"][0]["action"], "unchanged")

    def test_candidates_that_must_never_be_written_are_refused(self) -> None:
        for target in (".harness/policies/gate.json", ".github/hooks/harness.json", ".vscode/settings.json", ".git/config",
                       ".workspace/sandbox/requests/x/request.json", ".harness/runtime/state/a.json"):
            with self.subTest(target):
                request_id = self.new_request(session=SESSION)
                self.attempt(request_id)
                self.fill_assignment(request_id, 1, "builder")
                self.dispatch(request_id, "builder")
                self.output(request_id, 1, "builder", target, "x\n")
                self.submit(request_id, "builder", "passed", "--output", target)
                self.reviewer_round(request_id, 1)
                self.assertIn("不能回写", self.refused("promote", "--request", request_id, "--dry-run"))
                self.run_cli("request", "set-status", "--request", request_id, "--status", "abandoned", "--reason", "test")

    def test_an_override_that_drops_the_core_guardrails_does_not_open_promote(self) -> None:
        (self.root / ".harness" / "policies" / "gate.override.json").write_text(json.dumps({"guardrail_paths": ["docs/**"]}), encoding="utf-8")
        target = ".harness/policies/gate.json"
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.dispatch(request_id, "builder")
        self.output(request_id, 1, "builder", target, "x\n")
        self.submit(request_id, "builder", "passed", "--output", target)
        self.reviewer_round(request_id, 1)
        self.assertIn("不能回写", self.refused("promote", "--request", request_id, "--dry-run"))

    def test_a_candidate_changed_after_review_is_refused(self) -> None:
        request_id = self.passed_request()
        candidate = self.rd(request_id) / "handoffs" / "orchestrator" / "attempt-001" / "to-reviewer" / "candidate" / "src" / "slug.py"
        os.chmod(candidate, 0o644)
        candidate.write_text("evil\n", encoding="utf-8")
        self.assertIn("sha256", self.refused("promote", "--request", request_id, "--dry-run"))

    def test_promote_refuses_when_gate_json_cannot_be_read(self) -> None:
        request_id = self.passed_request()
        (self.root / ".harness" / "policies" / "gate.json").write_text("{ broken", encoding="utf-8")
        self.assertIn("gate.json", self.refused("promote", "--request", request_id, "--dry-run"))

    def test_the_real_promote_needs_the_persons_approval(self) -> None:
        request_id = self.passed_request()
        self.run_cli("promote", "--request", request_id, "--dry-run")
        message = self.refused("promote", "--request", request_id)
        self.assertIn("用户还没有批准", message)
        self.assertIn(f"request approve-promote --request {request_id}", message)
        self.assertIn("你不能自己运行它", message)
        self.assertFalse((self.root / "src" / "slug.py").exists())

    def test_the_dry_run_tells_the_agent_to_ask_the_person(self) -> None:
        request_id = self.passed_request()
        result = self.run_cli("promote", "--request", request_id, "--dry-run")
        self.assertFalse(result["approved"])
        self.assertIn("approve-promote", result["next"])

    def test_approve_only_works_for_a_person_at_a_terminal(self) -> None:
        request_id = self.passed_request()
        self.run_cli("promote", "--request", request_id, "--dry-run")
        message = self.refused("request", "approve-promote", "--request", request_id)  # stdin is not a TTY here, like an agent's
        self.assertIn("只能由用户在自己的终端", message)
        with self.assertRaises(layout.CommandError):
            promote.approve(self.root, request_id, reader=lambda _p: "x", interactive=False)
        self.assertNotIn("approved_plan_sha256", self.request(request_id)["promote"])
        completed = self.run_script(Path(__file__).resolve().parents[2] / ".harness" / "engine" / "cli.py", "request", "approve-promote", "--request", request_id,
                                    stdin="yes\n")  # piping the answer does not help either
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("approved_plan_sha256", self.request(request_id)["promote"])

    def test_approve_asks_for_the_code_and_shows_the_plan(self) -> None:
        request_id = self.passed_request()
        self.run_cli("promote", "--request", request_id, "--dry-run")
        shown = io.StringIO()
        asked: List[str] = []
        plan = self.request(request_id)["promote"]["plan_sha256"]
        promote.approve(self.root, request_id, reader=lambda prompt: asked.append(prompt) or plan[:8], interactive=True, out=shown)
        self.assertIn("src/slug.py", shown.getvalue())
        self.assertIn("create", shown.getvalue())
        self.assertIn(plan[:8], asked[0])
        self.assertEqual(self.request(request_id)["promote"]["approved_plan_sha256"], plan)

    def test_a_wrong_or_empty_answer_approves_nothing(self) -> None:
        request_id = self.passed_request()
        self.run_cli("promote", "--request", request_id, "--dry-run")
        for answer in ("", "yes", "y", "00000000"):
            with self.subTest(answer), self.assertRaises(layout.CommandError):
                self.approve(request_id, code=answer)
        self.assertNotIn("approved_plan_sha256", self.request(request_id)["promote"])
        self.assertIn("用户还没有批准", self.refused("promote", "--request", request_id))

    def test_approve_needs_a_dry_run_and_a_plan_that_has_not_changed(self) -> None:
        request_id = self.passed_request()
        with self.assertRaises(layout.CommandError) as raised:
            self.approve(request_id)
        self.assertIn("--dry-run", str(raised.exception))
        self.run_cli("promote", "--request", request_id, "--dry-run")
        self.write("src/slug.py", "changed after the dry-run\n")
        with self.assertRaises(layout.CommandError) as raised:
            self.approve(request_id, code="whatever")
        self.assertIn("重新运行 promote --dry-run", str(raised.exception))

    def test_an_approval_belongs_to_one_plan(self) -> None:
        request_id = self.passed_request()
        self.run_cli("promote", "--request", request_id, "--dry-run")
        self.approve(request_id)
        again = self.run_cli("promote", "--request", request_id, "--dry-run")  # same plan: the approval stays
        self.assertTrue(again["approved"])
        self.write("src/slug.py", "def slugify(s):\n    return s.upper()\n")  # the repo moved: a new plan
        self.assertIn("重新运行 --dry-run", self.refused("promote", "--request", request_id))
        changed = self.run_cli("promote", "--request", request_id, "--dry-run")
        self.assertFalse(changed["approved"])
        self.assertIn("用户还没有批准", self.refused("promote", "--request", request_id))

    def test_the_approval_is_recorded_with_the_promote(self) -> None:
        request_id = self.passed_request()
        self.promote_for_real(request_id)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["state"], record["approved_plan_sha256"], bool(record["approved_at"])), ("done", record["plan_sha256"], True))

    def test_approve_finds_the_one_request_that_waits_and_list_shows_it(self) -> None:
        request_id = self.passed_request()
        waiting = lambda: [r["request_id"] for r in self.run_cli("request", "list")["requests"] if r["waiting_for_approval"]]  # noqa: E731
        self.assertEqual(waiting(), [])
        with self.assertRaises(layout.CommandError) as raised:
            promote.approve(self.root, reader=lambda _p: "x", interactive=True, out=io.StringIO())
        self.assertIn("没有等待批准", str(raised.exception))
        self.run_cli("promote", "--request", request_id, "--dry-run")
        self.assertEqual(waiting(), [request_id])
        plan = self.request(request_id)["promote"]["plan_sha256"]
        result = promote.approve(self.root, reader=lambda _p: plan[:8], interactive=True, out=io.StringIO())  # no request id given
        self.assertTrue(result["approved"])
        self.assertEqual(waiting(), [])

    def test_approve_without_an_id_refuses_to_guess_between_requests(self) -> None:
        first = self.passed_request()
        self.run_cli("promote", "--request", first, "--dry-run")
        self.hook(payload("UserPromptSubmit", "sess-two", prompt="start"))
        second = self.new_request("second", session="sess-two")
        self.attempt(second)
        self.builder_round(second, 1)
        self.reviewer_round(second, 1)
        self.run_cli("promote", "--request", second, "--dry-run")
        with self.assertRaises(layout.CommandError) as raised:
            promote.approve(self.root, reader=lambda _p: "x", interactive=True, out=io.StringIO())
        self.assertIn(first, str(raised.exception))
        self.assertIn(second, str(raised.exception))

    def test_the_gate_denies_an_agent_that_runs_approve_and_lets_promote_through(self) -> None:
        request_id = self.passed_request()
        def ask(command: str) -> dict:
            return self.hook({**payload("PreToolUse", "s-gate", tool_name="run_in_terminal", tool_input={"command": command}), "tool_use_id": "1"})
        data = ask(f"python3 .harness/engine/cli.py request approve-promote --request {request_id}")
        self.assertEqual(data["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("用户在自己的终端", data["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(ask(f"python3 .harness/engine/cli.py promote --request {request_id}"), {})
        self.assertEqual(ask(f"python3 .harness/engine/cli.py promote --request {request_id} --dry-run"), {})


class LifecycleScenarioTests(RequestCase):
    """The shapes of the M4-8 scenarios, with no model in the loop."""

    def test_s1_one_round_passes_then_promote_then_accepted(self) -> None:
        request_id = self.passed_request()
        self.promote_for_real(request_id)
        self.run_cli("request", "set-status", "--request", request_id, "--status", "accepted")
        self.assertEqual(self.check(request_id, "--require-conclusion")["problems"], [])
        self.assertIsNone(self.session_state(SESSION)["active_request"])

    def test_s2_failed_review_then_a_second_attempt_passes(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.reviewer_round(request_id, 1, status="failed")
        self.attempt(request_id)
        self.builder_round(request_id, 2, body="def slugify(s):\n    return s.replace(' ', '-')\n")
        self.reviewer_round(request_id, 2)
        self.promote_for_real(request_id)
        self.assertEqual((self.root / "src" / "slug.py").read_text(encoding="utf-8"), "def slugify(s):\n    return s.replace(' ', '-')\n")
        self.run_cli("request", "set-status", "--request", request_id, "--status", "accepted")
        self.assertEqual(self.check(request_id, "--require-conclusion")["problems"], [])

    def test_s3_two_failures_then_the_limit_then_hitl(self) -> None:
        request_id = self.new_request()
        for number in (1, 2):
            self.attempt(request_id)
            self.builder_round(request_id, number)
            self.reviewer_round(request_id, number, status="failed")
        self.assertIn("--human-approved", self.refused("attempt", "new", "--request", request_id))
        self.run_cli("request", "set-status", "--request", request_id, "--status", "hitl", "--reason", "两轮都失败")
        self.assertEqual(self.check(request_id, "--require-conclusion")["problems"], [])
        self.assertIn("已经结束", self.refused("promote", "--request", request_id, "--dry-run"))

    def test_the_agent_is_told_the_session_id_each_prompt(self) -> None:
        output = self.hook(payload("UserPromptSubmit", "sess-told", prompt="hello"))
        self.assertIn("当前会话 id：sess-told", output["additionalContext"])


class ConcurrencyTests(RequestCase):
    def test_two_requests_in_two_sessions_at_once_do_not_clash(self) -> None:
        sessions = [f"sess-par-{n}" for n in range(4)]
        for session in sessions:
            self.hook(payload("UserPromptSubmit", session, prompt="start"))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda s: self.cli("request", "new", "--title", "same title", "--session-id", s), sessions))
        self.assertEqual([r.returncode for r in results], [0] * 4, [r.stderr for r in results])
        ids = {json.loads(r.stdout)["request_id"] for r in results}
        self.assertEqual(len(ids), 4)
        for session, result in zip(sessions, results):
            self.assertEqual(self.session_state(session)["active_request"], json.loads(result.stdout)["request_id"])

    def test_the_same_role_dispatched_at_once_succeeds_exactly_once(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.cli("dispatch", "--request", request_id, "--role", "builder"), range(6)))
        self.assertEqual(sorted(r.returncode == 0 for r in results), [False] * 5 + [True])
        self.assertEqual(len(self.request(request_id)["pending_dispatch"]), 1)
        self.assertEqual(self.check(request_id)["problems"], [])

    def test_attempts_opened_at_once_do_not_skip_or_repeat_a_number(self) -> None:
        request_id = self.new_request()
        self.ready_plan(request_id)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.cli("attempt", "new", "--request", request_id), range(4)))
        self.assertEqual(sum(r.returncode == 0 for r in results), 1)  # the next ones lack a handoff from the first
        self.assertEqual(self.request(request_id)["attempt"], 1)


class ReviewerAssignmentTests(RequestCase):
    """The reviewer's goal and acceptance criteria default to the builder's; the diff file is only for target repositories."""

    def test_the_reviewer_assignment_defaults_to_the_builders_goal_and_criteria(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        before = self.assignment(request_id, 1, "reviewer").read_text(encoding="utf-8")
        self.assertIn("（待填）", before)
        result = self.dispatch(request_id, "reviewer")
        self.assertTrue(result["assignment_copied_from_builder"])
        text = self.assignment(request_id, 1, "reviewer").read_text(encoding="utf-8")
        self.assertNotIn("（待填）", text)
        self.assertIn("写 slugify。", text)
        self.assertIn("slugify('A b') 返回 'a-b'", text)
        self.assertIn("## 先读什么", text)  # the rest of the template is untouched

    def test_a_reviewer_assignment_the_orchestrator_filled_is_not_overwritten(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        path = self.assignment(request_id, 1, "reviewer")
        path.write_text(path.read_text(encoding="utf-8").replace("## 目标\n\n（待填）", "## 目标\n\n只看命名").replace("## 验收标准\n\n（待填）", "## 验收标准\n\n- 函数叫 slugify"), encoding="utf-8")
        result = self.dispatch(request_id, "reviewer")
        self.assertNotIn("assignment_copied_from_builder", result)
        text = path.read_text(encoding="utf-8")
        self.assertIn("只看命名", text)
        self.assertNotIn("写 slugify。", text)

    def test_only_the_section_still_empty_is_copied(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        path = self.assignment(request_id, 1, "reviewer")
        path.write_text(path.read_text(encoding="utf-8").replace("## 目标\n\n（待填）", "## 目标\n\n只看命名"), encoding="utf-8")
        self.dispatch(request_id, "reviewer")
        text = path.read_text(encoding="utf-8")
        self.assertIn("只看命名", text)
        self.assertIn("slugify('A b') 返回 'a-b'", text)
        self.assertNotIn("（待填）", text)

    def test_a_request_without_target_repositories_gets_no_diff_file(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.reviewer_round(request_id, 1)
        package = self.rd(request_id) / "handoffs" / "orchestrator" / "attempt-001" / "to-reviewer"
        self.assertFalse((package / "candidate.diff").exists())


if __name__ == "__main__":
    unittest.main()
