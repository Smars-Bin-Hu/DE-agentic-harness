"""The L2 task (M7, B15-B18): start, the plan approval, the write scope, fetch/delete/diff, promote, rounds, the report.

The repositories are real git repositories made with `git init` in a temporary folder. Without git, these tests are skipped.
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import support  # noqa: F401  (puts the engine on sys.path)
from core import tasks
from modules.request import promote_target, task as task_ops
from modules.request.layout import CommandError
from support import payload, post_tool, pre_tool
from test_promote_target import git_text, porcelain
from test_request import SESSION
from test_target_inputs import TASK, TargetCase
from test_targets import GIT

PLAN = "# 计划\n\n给 a.sql 加一列。只改 bdtt_repo/src/a.sql。\n"
BIG = "".join(f"select {number} as c;\n" for number in range(120000))  # about 2 MB


@unittest.skipUnless(GIT, "git is not installed")
class TaskCase(TargetCase):
    def setUp(self) -> None:
        super().setUp()
        self.prompt("/l2 做任务 job1")
        self.task = self.root / TASK

    # --- helpers ------------------------------------------------------------------------------

    def prompt(self, text: str, session: str = SESSION) -> Dict[str, Any]:
        return self.hook(payload("UserPromptSubmit", session, prompt=text))

    def context(self, output: Dict[str, Any]) -> str:
        return output.get("additionalContext") or output.get("hookSpecificOutput", {}).get("additionalContext", "")

    def start(self, *extra: str, ok: bool = True) -> Any:
        return self.run_cli("task", "start", "--task", TASK, "--session-id", SESSION, *extra, ok=ok)

    def data(self) -> Dict[str, Any]:
        return json.loads((self.task / ".task" / "task.json").read_text(encoding="utf-8"))

    def write_plan(self, text: str = PLAN) -> None:  # type: ignore[override]
        (self.task / "PLAN.md").write_text(text, encoding="utf-8")

    def approve_plan(self, code: Optional[str] = None, out: Any = None, task: str = TASK) -> Dict[str, Any]:  # type: ignore[override]
        typed = code if code is not None else tasks.plan_digest(self.root, TASK)[:8]
        return task_ops.approve_plan(self.root, task, reader=lambda _prompt: typed, interactive=True, out=out or io.StringIO())

    def ready(self) -> None:
        """Started, with an approved plan."""
        self.start()
        self.write_plan()
        self.approve_plan()

    def dev(self, key: str, text: Optional[str] = None) -> Path:
        path = self.task / "DEV" / key
        if text is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return path

    def edit(self, path: str, session: str = SESSION) -> Dict[str, Any]:
        data = pre_tool(session, "create_file", {"filePath": path, "content": "x"})
        data["cwd"] = str(self.root)
        return self.hook(data)

    def decision(self, output: Dict[str, Any]) -> str:
        return output.get("hookSpecificOutput", {}).get("permissionDecision", "")

    def reason(self, output: Dict[str, Any]) -> str:
        return output["hookSpecificOutput"]["permissionDecisionReason"]

    def approve_promote(self, code: Optional[str] = None, out: Any = None) -> Dict[str, Any]:
        typed = code if code is not None else self.data()["promote"].get("plan_sha256", "")[:8]
        return task_ops.approve_promote(self.root, TASK, reader=lambda _prompt: typed, interactive=True, out=out or io.StringIO())

    def promoted(self) -> Dict[str, Any]:
        """A task with one changed file, promoted for real."""
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/src/a.sql")
        self.dev("bdtt_repo/src/a.sql", "select 1, 2;\n")
        self.run_cli("task", "promote", "--dry-run")
        self.approve_promote()
        return self.run_cli("task", "promote")


class StartTests(TaskCase):
    def test_start_makes_the_folders_and_puts_the_session_into_task_mode(self) -> None:
        result = self.start()
        self.assertEqual((result["task"], result["round"], result["resumed"], result["plan_approved"]), (TASK, 1, False, False))
        self.assertEqual(result["branch"], "feature/job1")
        self.assertEqual(result["target_repos"], ["b9td_repo", "bdtt_repo"])
        self.assertIn("PLAN.md", result["next"])
        self.assertIn("task approve-plan", result["next"])
        self.assertTrue((self.task / "DEV").is_dir())
        self.assertEqual(self.session_state(SESSION)["active_task"], TASK)
        self.assertEqual((self.data()["status"], self.data()["promote"]["state"]), ("open", "none"))

    def test_the_task_may_be_named_by_its_folder_name_or_an_absolute_path(self) -> None:
        self.assertEqual(self.run_cli("task", "start", "--task", "job1", "--session-id", SESSION)["task"], TASK)
        self.assertEqual(self.run_cli("task", "start", "--task", str(self.task), "--session-id", SESSION)["resumed"], True)

    def test_it_is_refused_at_l1_in_an_l3_request_for_a_missing_folder_and_for_an_unknown_session(self) -> None:
        self.prompt("/l1 小事")
        self.assertIn("只在 L2", self.start(ok=False)["stderr"])
        self.prompt("/l2 做任务")
        self.assertIn("没有会话", self.run_cli("task", "start", "--task", TASK, "--session-id", "nobody", ok=False)["stderr"])
        self.assertIn("任务目录", self.run_cli("task", "start", "--task", ".workspace/current_tasks/none", "--session-id", SESSION, ok=False)["stderr"])
        self.assertIn("current_tasks", self.run_cli("task", "start", "--task", "docs", "--session-id", SESSION, ok=False)["stderr"])
        request_id = self.target_request()
        self.assertIn("L3 请求", self.start(ok=False)["stderr"])
        self.run_cli("request", "set-status", "--request", request_id, "--status", "abandoned", "--reason", "x")
        self.assertEqual(self.start()["round"], 1)

    def test_starting_again_resumes_and_keeps_the_approval(self) -> None:
        self.ready()
        self.prompt("/l2 another day", session="sess-2")
        result = self.run_cli("task", "start", "--task", TASK, "--session-id", "sess-2")
        self.assertEqual((result["resumed"], result["new_round"], result["plan_approved"], result["round"]), (True, False, True, 1))
        self.assertEqual(self.data()["session_id"], "sess-2")
        self.assertIn("计划已批准", result["next"])

    def test_one_session_does_one_task_at_a_time(self) -> None:
        (self.root / ".workspace/current_tasks/job2").mkdir()
        self.start()
        self.assertIn("已经在做任务", self.run_cli("task", "start", "--task", "job2", "--session-id", SESSION, ok=False)["stderr"])
        self.run_cli("task", "close")
        self.assertEqual(self.run_cli("task", "start", "--task", "job2", "--session-id", SESSION)["task"], ".workspace/current_tasks/job2")

    def test_every_prompt_of_a_task_says_where_it_stands(self) -> None:
        self.assertIn("task start", self.context(self.prompt("/l2 hello")))  # free L2: the one-line pointer
        self.assertNotIn("任务模式（L2）", self.context(self.prompt("hello")))
        self.start()
        text = self.context(self.prompt("继续"))
        self.assertIn(f"任务模式（L2）：任务目录 {TASK}", text)
        self.assertIn("把计划写到", text)
        self.write_plan()
        self.assertIn("还没有经用户批准", self.context(self.prompt("继续")))
        self.approve_plan()
        self.assertIn("计划已批准", self.context(self.prompt("继续")))
        self.run_cli("task", "close")
        self.assertNotIn("任务模式（L2）", self.context(self.prompt("继续")))
        self.assertEqual(self.run_cli("stats")["task_mode_prompts"], 3)

    def test_without_target_repositories_a_task_only_fills_dev(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        result = self.start()
        self.assertNotIn("branch", result)
        self.write_plan()
        self.approve_plan()
        self.dev("notes/design.md", "# design\n")
        shown = self.run_cli("task", "diff")
        self.assertEqual([(f["path"], f["action"]) for f in shown["files"]], [("notes/design.md", "create")])
        self.assertIn("没有配置目标仓库", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        self.assertIn("没有配置目标仓库", self.run_cli("task", "fetch", "bdtt_repo/src/a.sql", ok=False)["stderr"])
        self.assertEqual(self.run_cli("task", "close")["status"], "closed")


class PlanApprovalTests(TaskCase):
    def test_before_the_approval_only_the_plan_is_written(self) -> None:
        self.start()
        self.assertEqual(self.edit(f"{TASK}/PLAN.md"), {})
        for path in (f"{TASK}/DEV/bdtt_repo/src/a.sql", f"{TASK}/REQ/req.md", "docs/x.md", "/tmp/outside.txt"):
            with self.subTest(path):
                output = self.edit(path)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn("只能写", self.reason(output))
                self.assertIn("task approve-plan", self.reason(output))
        self.assertIn("把计划写到", self.run_cli("task", "fetch", "bdtt_repo/src/a.sql", ok=False)["stderr"])
        self.write_plan()
        self.assertIn("还没有经用户批准", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        self.assertIn("还没有经用户批准", self.run_cli("task", "delete", "bdtt_repo/src/a.sql", ok=False)["stderr"])

    def test_after_the_approval_only_dev_and_the_plan_are_written(self) -> None:
        self.ready()
        for path in (f"{TASK}/DEV/bdtt_repo/src/a.sql", f"{TASK}/DEV/new/deep/file.sql", f"{TASK}/PLAN.md", str(self.task.resolve() / "DEV" / "x.sql")):
            with self.subTest(path):
                self.assertEqual(self.edit(path), {})
        for path in (f"{TASK}/REQ/req.md", f"{TASK}/DEV", f"{TASK}/DEV2/x", "docs/x.md", "/tmp/outside.txt", f"{TASK}/DEV/../REQ/a"):
            with self.subTest(path):
                output = self.edit(path)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn("DEV/", self.reason(output))
        # files only the CLI writes, and the target repository itself, stay closed
        self.assertEqual(self.decision(self.edit(f"{TASK}/.task/task.json")), "deny")
        self.assertEqual(self.decision(self.edit(f"{TASK}/PROMOTE-PLAN.diff")), "deny")
        self.assertIn("只能由 promote 写", self.reason(self.edit(str(self.bdtt / "src" / "a.sql"))))

    def test_the_code_is_bound_to_the_plan_and_the_screen_only_names_the_file(self) -> None:
        self.start()
        with self.assertRaises(CommandError):
            self.approve_plan()  # no plan yet
        self.write_plan()
        screen = io.StringIO()
        with self.assertRaises(CommandError):
            self.approve_plan(code="wrong", out=screen)
        self.assertEqual(self.data()["plan"], {})
        self.assertTrue(self.approve_plan(out=screen)["approved"])
        self.assertIn(f"{TASK}/PLAN.md", screen.getvalue())
        self.assertNotIn("给 a.sql 加一列", screen.getvalue())
        self.assertEqual(self.data()["plan"]["approved_sha256"], tasks.plan_digest(self.root, TASK))

    def test_a_plan_changed_after_the_approval_closes_dev_again(self) -> None:
        self.ready()
        self.assertEqual(self.edit(f"{TASK}/DEV/a.sql"), {})
        self.write_plan(PLAN + "\n再加一个文件。\n")
        self.assertIn("批准之后改过", self.reason(self.edit(f"{TASK}/DEV/a.sql")))
        self.approve_plan()
        self.assertEqual(self.edit(f"{TASK}/DEV/a.sql"), {})

    def test_only_a_person_at_a_terminal_approves(self) -> None:
        self.start()
        self.write_plan()
        self.assertIn("只能由用户在自己的终端里手动运行", self.run_cli("task", "approve-plan", ok=False)["stderr"])
        for command in ("python3 .harness/engine/cli.py task approve-plan", f"harness task approve-promote --task {TASK}", "python .harness/engine/cli.py task recover"):
            data = pre_tool(SESSION, "run_in_terminal", {"command": command})
            self.assertEqual(self.decision(self.hook(data)), "deny", command)

    def test_no_task_no_rule_and_a_closed_task_binds_nobody(self) -> None:
        self.assertEqual(self.edit("docs/x.md"), {})  # free L2
        self.start()
        self.assertEqual(self.decision(self.edit("docs/x.md")), "deny")
        self.run_cli("task", "close")
        self.assertEqual(self.edit("docs/x.md"), {})

    def test_a_verifier_of_a_task_is_told_to_read_the_diff(self) -> None:
        self.ready()
        output = self.hook(payload("SubagentStart", SESSION, agent_id="a1", agent_type="verifier"))
        text = self.context(output)
        self.assertIn("task diff", text)
        self.assertIn("CHANGES.diff", text)
        self.assertIn("不要用 git diff", text)


class VerifyTests(TaskCase):
    """The verifier choice of a task: written once, it holds for every later prompt of the task."""

    VERIFIER = {"agentName": "verifier", "prompt": "check it", "description": "check"}

    def call_verifier(self, session: str = SESSION) -> Dict[str, Any]:
        return self.hook(pre_tool(session, "runSubagent", self.VERIFIER))

    def edited(self, path: str) -> None:
        tool_input = {"filePath": path, "content": "x"}
        for data in (pre_tool(SESSION, "create_file", tool_input), post_tool(SESSION, "create_file", tool_input)):
            data["cwd"] = str(self.root)
            self.hook(data)

    def blocked(self) -> bool:
        output = self.hook(payload("Stop", SESSION, stop_hook_active=False))
        return output.get("hookSpecificOutput", {}).get("decision") == "block"

    def test_the_marker_of_the_first_prompt_holds_for_the_later_prompts(self) -> None:
        self.prompt("/l2 [verify] 做任务 job1")
        self.assertEqual(self.start()["verify"], "on")
        self.assertEqual(self.data()["verify"], "on")
        self.write_plan()
        self.approve_plan()
        text = self.context(self.prompt("计划批准了"))
        self.assertIn("只允许 verifier", text)
        self.assertNotIn("没有开启 verifier 复核", text)
        self.assertIn("这个任务开启了 verifier 复核", text)
        self.assertEqual(self.call_verifier(), {})
        self.prompt("批准了")
        self.assertEqual(self.call_verifier(), {})

    def test_without_a_marker_the_verifier_stays_off(self) -> None:
        self.start()
        self.assertEqual(self.data()["verify"], "")
        text = self.context(self.prompt("计划批准了"))
        self.assertIn("子 agent：不允许", text)
        self.assertEqual(self.decision(self.call_verifier()), "deny")

    def test_a_marker_in_a_later_prompt_changes_the_task(self) -> None:
        self.start()
        self.assertIn("这个任务开启了 verifier 复核", self.context(self.prompt("[verify] 交付前复核一次")))
        self.assertEqual(self.data()["verify"], "on")
        self.prompt("继续")
        self.assertEqual(self.call_verifier(), {})
        self.assertIn("这个任务关闭了 verifier 复核", self.context(self.prompt("[no-verify] 不用复核了")))
        self.assertEqual(self.data()["verify"], "off")
        self.prompt("继续")
        self.assertEqual(self.decision(self.call_verifier()), "deny")
        self.assertEqual([event["what"] for event in self.data()["events"]].count("verify"), 2)

    def test_the_plan_is_not_the_verifiers_to_review(self) -> None:
        self.prompt("/l2 [verify] 做任务 job1")
        self.start()
        self.edited(f"{TASK}/PLAN.md")
        self.assertFalse(self.blocked())  # the person reviews the plan
        self.write_plan()
        self.approve_plan()
        self.prompt("计划批准了")
        self.edited(f"{TASK}/DEV/a.txt")
        self.assertTrue(self.blocked())  # no marker in this prompt, the task's choice counts

    def test_the_choice_ends_with_the_task_and_comes_back_when_it_is_resumed(self) -> None:
        self.prompt("/l2 [verify] 做任务 job1")
        self.start()
        self.run_cli("task", "close")
        self.prompt("另一件事")
        self.assertEqual(self.decision(self.call_verifier()), "deny")
        self.prompt("/l2 接着做 job1", "s2")
        self.assertEqual(self.run_cli("task", "start", "--task", TASK, "--session-id", "s2")["verify"], "on")
        self.assertEqual(self.call_verifier("s2"), {})  # the same prompt that resumed the task
        self.assertIn("verifier 复核：开启", (self.root / self.run_cli("task", "report", "--task", TASK)["report"]).read_text(encoding="utf-8"))


class FetchDiffTests(TaskCase):
    def test_fetch_copies_the_main_version_into_dev_with_the_repository_layout(self) -> None:
        self.ready()
        result = self.run_cli("task", "fetch", "bdtt_repo/src/a.sql", "b9td_repo/a.sql")
        self.assertEqual(result["fetched"], [f"{TASK}/DEV/b9td_repo/a.sql", f"{TASK}/DEV/bdtt_repo/src/a.sql"])
        self.assertEqual(self.dev("bdtt_repo/src/a.sql").read_text(encoding="utf-8"), "select 1;\n")
        self.assertEqual((self.task / ".task" / "base" / "bdtt_repo" / "src" / "a.sql").read_text(encoding="utf-8"), "select 1;\n")
        data = self.data()
        self.assertEqual(data["target_files"]["bdtt_repo/src/a.sql"]["blob"], self.blob(self.bdtt, "src/a.sql"))
        self.assertEqual(data["targets"]["bdtt_repo"]["base_commit"], self.main_commit(self.bdtt))
        self.assert_clean()

    def assert_clean(self) -> None:
        self.assertEqual(porcelain(self.bdtt), [])
        self.assertEqual(git_text(self.bdtt, "symbolic-ref", "--short", "HEAD"), "main")

    def test_a_folder_is_fetched_whole_and_a_wrong_name_is_refused(self) -> None:
        self.ready()
        self.assertEqual(len(self.run_cli("task", "fetch", "bdtt_repo/src")["fetched"]), 2)
        self.assertIn("没有", self.run_cli("task", "fetch", "bdtt_repo/src/none.sql", ok=False)["stderr"])
        self.assertIn("没有叫", self.run_cli("task", "fetch", "nope_repo/a.sql", ok=False)["stderr"])

    def test_a_refused_path_is_not_fetched_for_editing(self) -> None:
        self.override({"repos_root": str(self.repos), "refused_paths": [".git/**", "docs/**"]})
        self.ready()
        self.assertIn("不能回写", self.run_cli("task", "fetch", "bdtt_repo/docs/x.md", ok=False)["stderr"])

    def test_fetching_again_keeps_the_edits_unless_overwrite(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/src/a.sql")
        self.dev("bdtt_repo/src/a.sql", "select 1, 2;\n")
        result = self.run_cli("task", "fetch", "bdtt_repo/src/a.sql")
        self.assertEqual((result["fetched"], result["kept"]), ([], ["bdtt_repo/src/a.sql"]))
        self.assertEqual(self.dev("bdtt_repo/src/a.sql").read_text(encoding="utf-8"), "select 1, 2;\n")
        self.run_cli("task", "fetch", "--overwrite", "bdtt_repo/src/a.sql")
        self.assertEqual(self.dev("bdtt_repo/src/a.sql").read_text(encoding="utf-8"), "select 1;\n")

    def test_a_large_file_and_crlf_arrive_byte_for_byte_and_the_diff_holds_only_the_change(self) -> None:
        (self.bdtt / "big.sql").write_text(BIG, encoding="utf-8", newline="\n")
        (self.bdtt / "crlf.sql").write_bytes(b"select 1;\r\nselect 2;\r\n")
        git_text(self.bdtt, "-c", "core.autocrlf=false", "add", "-A")  # with autocrlf=true, git would store this CRLF file as LF
        git_text(self.bdtt, "-c", "core.autocrlf=false", "commit", "-q", "-m", "big")
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/big.sql", "bdtt_repo/crlf.sql")
        self.assertEqual(self.dev("bdtt_repo/big.sql").read_bytes(), BIG.encode("utf-8"))
        self.assertEqual(self.dev("bdtt_repo/crlf.sql").read_bytes(), b"select 1;\r\nselect 2;\r\n")
        self.dev("bdtt_repo/big.sql", BIG.replace("select 60000 as c;", "select 60000 as changed;"))
        shown = self.run_cli("task", "diff")
        self.assertEqual(shown["files"], [{"path": "bdtt_repo/big.sql", "action": "modify", "added": 1, "removed": 1}])
        self.assertEqual(shown["unchanged"], 1)
        text = (self.task / "CHANGES.diff").read_text(encoding="utf-8")
        self.assertEqual(shown["diff_file"], f"{TASK}/CHANGES.diff")
        self.assertIn("+select 60000 as changed;", text)
        self.assertLess(len(text.splitlines()), 20)

    def test_diff_shows_new_changed_and_deleted_files(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/src")
        self.dev("bdtt_repo/src/a.sql", "select 1, 2;\n")
        self.dev("bdtt_repo/src/new.sql", "select 3;\n")
        self.run_cli("task", "delete", "bdtt_repo/src/b.sql")
        self.assertFalse(self.dev("bdtt_repo/src/b.sql").exists())
        shown = self.run_cli("task", "diff")
        self.assertEqual(sorted((f["path"], f["action"]) for f in shown["files"]), [
            ("bdtt_repo/src/a.sql", "modify"), ("bdtt_repo/src/b.sql", "delete"), ("bdtt_repo/src/new.sql", "create"),
        ])
        text = (self.task / "CHANGES.diff").read_text(encoding="utf-8")
        for needle in ("-select 1;", "+select 1, 2;", "+select 3;", "deleted file", "-select 2;"):
            self.assertIn(needle, text)

    def test_delete_needs_a_fetched_file_and_fetching_it_again_takes_the_delete_back(self) -> None:
        self.ready()
        self.assertIn("不是这个任务从 main 取过的文件", self.run_cli("task", "delete", "bdtt_repo/src/b.sql", ok=False)["stderr"])
        self.run_cli("task", "fetch", "bdtt_repo/src/b.sql")
        self.assertEqual(self.run_cli("task", "delete", "bdtt_repo/src/b.sql")["deletes"], ["bdtt_repo/src/b.sql"])
        self.run_cli("task", "fetch", "bdtt_repo/src/b.sql")
        self.assertEqual(self.data()["deletes"], [])
        self.assertTrue(self.dev("bdtt_repo/src/b.sql").is_file())


class PromoteTests(TaskCase):
    def test_dry_run_writes_the_review_file_and_changes_nothing(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/src/a.sql")
        self.dev("bdtt_repo/src/a.sql", "select 1, 2;\n")
        result = self.run_cli("task", "promote", "--dry-run")
        self.assertEqual((result["dry_run"], result["branch"], result["approved"]), (True, "feature/job1", False))
        self.assertEqual([(f["path"], f["action"], f["added"], f["removed"]) for f in result["files"]], [("bdtt_repo/src/a.sql", "modify", 1, 1)])
        self.assertNotIn("source", result["files"][0])
        self.assertEqual(result["review_file"], f"{TASK}/PROMOTE-PLAN.diff")
        self.assertIn("task approve-promote", result["next"])
        review = (self.task / "PROMOTE-PLAN.diff").read_text(encoding="utf-8")
        self.assertIn("+select 1, 2;", review)
        self.assertIn("# repository bdtt_repo: main at", review)
        self.assertEqual(porcelain(self.bdtt), [])
        self.assertEqual(self.data()["promote"]["state"], "dry_run")

    def test_the_real_run_needs_the_persons_approval_of_that_plan(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/src/a.sql")
        self.dev("bdtt_repo/src/a.sql", "select 1, 2;\n")
        self.assertIn("还没有对应的 --dry-run", self.run_cli("task", "promote", ok=False)["stderr"])
        self.run_cli("task", "promote", "--dry-run")
        self.assertIn("还没有批准", self.run_cli("task", "promote", ok=False)["stderr"])
        screen = io.StringIO()
        with self.assertRaises(CommandError):
            self.approve_promote(code="no", out=screen)
        self.approve_promote(out=screen)
        self.assertIn("modify    bdtt_repo/src/a.sql  (+1 -1)", screen.getvalue())
        self.assertIn(f"{TASK}/PROMOTE-PLAN.diff", screen.getvalue())
        self.assertNotIn("+select 1, 2;", screen.getvalue())
        self.dev("bdtt_repo/src/a.sql", "select 1, 2, 3;\n")  # changed after the approval
        self.assertIn("变了", self.run_cli("task", "promote", ok=False)["stderr"])
        self.assertEqual(porcelain(self.bdtt), [])

    def test_promote_writes_a_new_branch_and_commits_nothing(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/src")
        self.dev("bdtt_repo/src/a.sql", "select 1, 2;\n")
        self.dev("bdtt_repo/src/new/c.sql", "select 3;\n")
        self.run_cli("task", "delete", "bdtt_repo/src/b.sql")
        self.run_cli("task", "promote", "--dry-run")
        screen = io.StringIO()
        self.approve_promote(out=screen)
        self.assertIn("会被删除", screen.getvalue())
        result = self.run_cli("task", "promote")
        self.assertEqual(result["dry_run"], False)
        self.assertEqual(git_text(self.bdtt, "symbolic-ref", "--short", "HEAD"), "feature/job1")
        self.assertEqual(porcelain(self.bdtt), [" D src/b.sql", " M src/a.sql", "?? src/new/"])
        self.assertEqual(git_text(self.bdtt, "rev-parse", "HEAD"), self.main_commit(self.bdtt))  # no commit
        self.assertEqual((self.bdtt / "src" / "a.sql").read_text(encoding="utf-8"), "select 1, 2;\n")
        self.assertEqual(porcelain(self.b9td), [])
        data = self.data()
        self.assertEqual(data["promote"]["state"], "done")
        patch = (self.root / data["promote"]["patch"]).read_text(encoding="utf-8")
        self.assertEqual(data["promote"]["patch"], f"{TASK}/DEV/job1.patch")
        self.assertIn("+select 1, 2;", patch)
        self.assertEqual((self.task / "DEV" / "_deleted" / "bdtt_repo" / "src" / "b.sql").read_text(encoding="utf-8"), "select 2;\n")
        self.assertIn("已经 promote 过", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        # the backups promote left in DEV/ are not results
        self.assertEqual(sorted(key for key, _path in task_ops.dev_files(self.root, TASK)), ["bdtt_repo/src/a.sql", "bdtt_repo/src/new/c.sql"])

    def test_a_repository_that_converts_line_endings_shows_only_the_results(self) -> None:
        """`core.autocrlf=true` is the git default on Windows: main holds LF, the working tree may hold CRLF."""
        git_text(self.bdtt, "config", "core.autocrlf", "true")
        (self.bdtt / "src" / "b.sql").write_bytes(b"select 2;\r\n")  # what a Windows checkout leaves in the working tree
        git_text(self.bdtt, "add", "src/b.sql")  # same blob (git converts it back); the index now knows the file's size
        self.assertEqual(porcelain(self.bdtt), [])
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/src/a.sql")
        self.assertEqual(self.dev("bdtt_repo/src/a.sql").read_bytes(), b"select 1;\n")  # the main version, byte for byte
        self.dev("bdtt_repo/src/a.sql").write_bytes(b"select 1, 2;\n")
        self.run_cli("task", "promote", "--dry-run")
        self.approve_promote()
        self.run_cli("task", "promote")
        self.assertEqual(porcelain(self.bdtt), [" M src/a.sql"])
        self.assertEqual((self.bdtt / "src" / "a.sql").read_bytes(), b"select 1, 2;\n")
        self.assertEqual((self.bdtt / "src" / "b.sql").read_bytes(), b"select 2;\r\n")

    def test_the_checks_of_the_l3_promote_apply(self) -> None:
        self.ready()
        self.dev("bdtt_repo/src/a.sql", "select 1, 2;\n")  # written without a fetch
        self.assertIn("task fetch bdtt_repo/src/a.sql", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        self.assertEqual(self.run_cli("task", "fetch", "bdtt_repo/src/a.sql")["kept"], ["bdtt_repo/src/a.sql"])  # the edit stays
        self.assertEqual(self.run_cli("task", "promote", "--dry-run")["files"][0]["action"], "modify")
        self.run_cli("task", "fetch", "--overwrite", "bdtt_repo/src/a.sql")
        self.assertIn("完全一样", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        self.dev("bdtt_repo/src/a.sql", "select 1, 2;\n")
        self.dev("notes/x.md", "n\n")
        self.assertIn("不是已配置的目标仓库", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        self.dev("notes/x.md").unlink()
        (self.bdtt / "dirty.txt").write_text("x\n", encoding="utf-8")
        self.assertIn("工作区不干净", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        (self.bdtt / "dirty.txt").unlink()
        git_text(self.bdtt, "branch", "feature/job1")
        message = self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"]
        self.assertIn("已经存在", message)
        self.assertIn("task set-branch", message)
        self.assertEqual(self.run_cli("task", "set-branch", "--branch", "feature/job1_b")["branch"], "feature/job1_b")
        self.assertEqual(self.run_cli("task", "promote", "--dry-run")["branch"], "feature/job1_b")
        (self.bdtt / "src" / "a.sql").write_text("select 0;\n", encoding="utf-8")  # main moves under the task
        git_text(self.bdtt, "commit", "-qam", "moved")
        self.assertIn("在 main 上变了", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])

    def test_a_promote_that_stops_halfway_is_recovered_by_the_person(self) -> None:
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/src/a.sql", "b9td_repo/a.sql")
        self.dev("bdtt_repo/src/a.sql", "select 1, 2;\n")
        self.dev("b9td_repo/a.sql", "select 9, 9;\n")
        self.run_cli("task", "promote", "--dry-run")
        self.approve_promote()
        real = promote_target.write_repo

        def failing(root: Path, found: Any, repo: Dict[str, Any], branch: str, written: List[Dict[str, Any]]) -> bool:
            if repo["name"] == "bdtt_repo":
                real(root, found, repo, branch, written)
                raise OSError("disk full")
            return real(root, found, repo, branch, written)

        with mock.patch.object(promote_target, "write_repo", failing):
            with self.assertRaises(CommandError) as caught:
                task_ops.run_promote(self.root, TASK, False)
        self.assertIn("task recover --task", str(caught.exception))
        self.assertEqual(self.data()["promote"]["state"], "partial")
        self.assertIn("中途出错", self.run_cli("task", "close", ok=False)["stderr"])
        self.assertIn("task recover", self.run_cli("task", "promote", "--dry-run", ok=False)["stderr"])
        code = self.data()["promote"]["plan_sha256"][:8]
        screen = io.StringIO()
        result = task_ops.recover(self.root, TASK, reader=lambda _p: code, interactive=True, out=screen)
        self.assertTrue(result["recovered"])
        self.assertIn("restore", screen.getvalue())
        for repo in (self.bdtt, self.b9td):
            self.assertEqual(porcelain(repo), [])
            self.assertEqual(git_text(repo, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(self.data()["promote"]["state"], "none")
        self.assertEqual(self.run_cli("task", "promote", "--dry-run")["dry_run"], True)


class RoundAndReportTests(TaskCase):
    def test_after_a_promote_starting_again_opens_a_new_round_with_a_new_plan(self) -> None:
        self.promoted()
        self.run_cli("task", "close")
        git_text(self.bdtt, "commit", "-qam", "the person commits")
        git_text(self.bdtt, "switch", "-q", "main")
        result = self.start()
        self.assertEqual((result["round"], result["new_round"], result["plan_approved"], result["branch"]), (2, True, False, "feature/job1_r2"))
        self.assertTrue((self.task / "DEV_r1" / "bdtt_repo" / "src" / "a.sql").is_file())
        self.assertEqual(list((self.task / "DEV").iterdir()), [])
        self.assertEqual((self.task / "PLAN_r1.md").read_text(encoding="utf-8"), PLAN)  # the old plan cannot be approved again
        self.assertFalse((self.task / "PLAN.md").exists())
        self.assertIn("把计划写到", result["next"])
        data = self.data()
        self.assertEqual((data["target_files"], data["deletes"], data["plan"], data["promote"]), ({}, [], {}, {"state": "none"}))
        self.assertEqual(data["rounds"][0]["promote"]["state"], "done")
        self.assertEqual(self.decision(self.edit(f"{TASK}/DEV/x.sql")), "deny")  # the old approval does not carry over
        self.write_plan(PLAN + "第二轮。\n")
        self.approve_plan()
        self.run_cli("task", "fetch", "bdtt_repo/src/a.sql")
        self.dev("bdtt_repo/src/a.sql", "select 1, 2, 3;\n")
        self.assertEqual(self.run_cli("task", "promote", "--dry-run")["branch"], "feature/job1_r2")

    def test_close_releases_the_session_and_writes_the_report(self) -> None:
        self.promoted()
        self.hook(post_tool(SESSION, "runSubagent", {"agentName": "verifier", "prompt": "check", "description": "v"}, response="VERDICT: PASS\nok"))
        result = self.run_cli("task", "close", "--reason", "done")
        self.assertEqual((result["status"], result["session_released"], result["report"]), ("closed", True, ".workspace/reports/task-job1.md"))
        self.assertIsNone(self.session_state(SESSION)["active_task"])
        text = (self.root / result["report"]).read_text(encoding="utf-8")
        for needle in (
            "# 任务报告：job1", "计划：由人批准于", "已回写到目标仓库的新分支", "回写由人批准于", "modify bdtt_repo/src/a.sql", "| bdtt_repo/src/a.sql | modify | 1 | 1 |",
            "> 给 a.sql 加一列", "人批准计划", "人批准回写", "回写到新分支", "关闭", "## hook 日志", "PASS", f"{TASK}/DEV/job1.patch",
        ):
            self.assertIn(needle, text)
        self.assertIn("任务已经关闭", self.run_cli("task", "fetch", "--task", TASK, "bdtt_repo/src/a.sql", ok=False)["stderr"])
        self.assertIn("没有进行中的任务", self.run_cli("task", "fetch", "bdtt_repo/src/a.sql", ok=False)["stderr"])
        self.assertEqual(self.run_cli("task", "report")["report"], ".workspace/reports/task-job1.md")
        denied = self.edit(".workspace/reports/task-job1.md")
        self.assertEqual(self.decision(denied), "deny")

    def test_status_says_what_comes_next(self) -> None:
        self.start()
        shown = self.run_cli("task", "status")
        self.assertEqual((shown["plan_written"], shown["plan_approved"], shown["promote"]), (False, False, "none"))
        self.ready()
        self.run_cli("task", "fetch", "bdtt_repo/src/a.sql")
        shown = self.run_cli("task", "status")
        self.assertEqual((shown["plan_approved"], shown["fetched"]), (True, ["bdtt_repo/src/a.sql"]))
        self.assertIn("task promote --dry-run", shown["next"])


if __name__ == "__main__":
    unittest.main()
