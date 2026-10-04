"""promote can delete files (B13): `handoff submit --delete`, the reviewer's package, the plan, the run, the backup and the recovery."""

from __future__ import annotations

import io
import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, List

import support  # noqa: F401  (puts the engine on sys.path)
from modules.request import promote, promote_target
from test_promote_target import BRANCH, PromoteCase, git_text, porcelain
from test_request import SESSION
from test_target_inputs import TASK
from test_targets import run_git


class DeleteCase(PromoteCase):
    def delete_flow(self, deletes: List[str], outputs: Any = None, branch: str = BRANCH) -> str:
        """A request whose builder deletes `deletes` (`<repo>/<path>`) and writes `outputs`; the reviewer passed."""
        request_id = self.target_request(branch=branch)
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        fetched = list(deletes) + [key for key in (outputs or {}) if key in ("bdtt_repo/src/a.sql",)]
        extra: List[str] = []
        for spec in fetched:
            extra += ["--from-target", spec]
        self.run_cli("dispatch", "--request", request_id, "--role", "builder", *extra)
        args: List[str] = []
        for key, text in (outputs or {}).items():
            self.output(request_id, 1, "builder", key, text)
            args += ["--output", key]
        for key in deletes:
            args += ["--delete", key]
        self.submit(request_id, "builder", "passed", *args)
        self.reviewer_round(request_id, 1)
        return request_id

    def package(self, request_id: str) -> Path:
        return self.rd(request_id) / "handoffs" / "orchestrator" / "attempt-001" / "to-reviewer"


class HandoffTests(DeleteCase):
    def test_the_handoff_records_the_deletes_and_the_reviewer_gets_the_old_file_and_a_diff(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        handoff = json.loads((self.rd(request_id) / "handoffs" / "builder" / "attempt-001" / "handoff.json").read_text(encoding="utf-8"))
        self.assertEqual((handoff["outputs"], handoff["deletes"]), ([], ["bdtt_repo/src/b.sql"]))
        manifest = json.loads((self.package(request_id) / "manifest.json").read_text(encoding="utf-8"))
        deleted = [item for item in manifest["files"] if item["purpose"] == "deleted"]
        self.assertEqual([item["path"] for item in deleted], ["base/bdtt_repo/src/b.sql"])
        self.assertEqual((self.package(request_id) / "base" / "bdtt_repo" / "src" / "b.sql").read_text(encoding="utf-8"), "select 2;\n")
        diff = (self.package(request_id) / "candidate.diff").read_text(encoding="utf-8")
        for needle in ("diff --git a/bdtt_repo/src/b.sql", "deleted file", "+++ /dev/null", "-select 2;"):
            self.assertIn(needle, diff)

    def test_a_handoff_without_deletes_has_no_deletes_key(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        handoff = json.loads((self.rd(request_id) / "handoffs" / "builder" / "attempt-001" / "handoff.json").read_text(encoding="utf-8"))
        self.assertNotIn("deletes", handoff)

    def test_a_delete_needs_a_fetched_file_a_clean_path_and_a_builder(self) -> None:
        request_id = self.target_request(branch=BRANCH)
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.run_cli("dispatch", "--request", request_id, "--role", "builder", "--from-target", "bdtt_repo/src/b.sql")
        self.assertIn("取过", self.refused("handoff", "submit", "--request", request_id, "--role", "builder", "--status", "passed", "--summary", "x", "--delete", "bdtt_repo/src/a.sql"))
        self.assertIn("第一段要是仓库名", self.refused("handoff", "submit", "--request", request_id, "--role", "builder", "--status", "passed", "--summary", "x", "--delete", "nope/src/b.sql"))
        self.output(request_id, 1, "builder", "bdtt_repo/src/b.sql", "")
        self.assertIn("同时出现", self.refused("handoff", "submit", "--request", request_id, "--role", "builder", "--status", "passed", "--summary", "x", "--output", "bdtt_repo/src/b.sql", "--delete", "bdtt_repo/src/b.sql"))
        self.assertIn("只有 builder", self.refused("handoff", "submit", "--request", request_id, "--role", "reviewer", "--status", "passed", "--summary", "x", "--delete", "bdtt_repo/src/b.sql"))

    def test_a_refused_path_cannot_be_deleted(self) -> None:
        self.override({"repos_root": str(self.repos), "repos": {"bdtt_repo": {"refused_paths": ["docs/**"]}}})
        request_id = self.target_request(branch=BRANCH)
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.run_cli("dispatch", "--request", request_id, "--role", "builder", "--from-target", "bdtt_repo/docs/x.md")
        self.assertIn("不能回写的路径", self.refused("handoff", "submit", "--request", request_id, "--role", "builder", "--status", "passed", "--summary", "x", "--delete", "bdtt_repo/docs/x.md"))

    def test_without_target_repositories_there_is_no_delete(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.dispatch(request_id, "builder")
        self.assertIn("目标仓库", self.refused("handoff", "submit", "--request", request_id, "--role", "builder", "--status", "passed", "--summary", "x", "--delete", "src/slug.py"))

    def test_a_passed_builder_needs_an_output_or_a_delete(self) -> None:
        request_id = self.target_request(branch=BRANCH)
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.run_cli("dispatch", "--request", request_id, "--role", "builder")
        self.assertIn("--delete", self.refused("handoff", "submit", "--request", request_id, "--role", "builder", "--status", "passed", "--summary", "x"))


class PlanAndRunTests(DeleteCase):
    def test_the_plan_lists_the_delete(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        result = self.dry_run(request_id)
        self.assertEqual([(f["path"], f["action"]) for f in result["files"]], [("bdtt_repo/src/b.sql", "delete")])
        self.assertEqual((result["files"][0]["added"], result["files"][0]["removed"]), (0, 1))
        self.assertNotIn("diff", result["files"][0])
        self.assertEqual(self.request(request_id)["promote"]["state"], "dry_run")

    def test_the_approval_screen_says_which_files_are_deleted(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        self.dry_run(request_id)
        screen = io.StringIO()
        plan = self.request(request_id)["promote"]["plan_sha256"]
        promote.approve(self.root, request_id, reader=lambda _prompt: plan[:8], interactive=True, out=screen)
        text = screen.getvalue()
        self.assertIn("delete", text)
        self.assertIn("会被删除", text)
        review = (self.rd(request_id) / "promote-plan.diff").read_text(encoding="utf-8")  # the diff is read in the editor
        self.assertIn("deleted file", review)
        self.assertIn("-select 2;", review)
        self.assertIn("promote-plan.diff", text)

    def test_the_file_is_deleted_on_the_new_branch_and_nothing_is_committed(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        main = self.main_commit(self.bdtt)
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual(git_text(self.bdtt, "symbolic-ref", "--short", "HEAD"), BRANCH)
        self.assertEqual(git_text(self.bdtt, "rev-parse", "HEAD"), main)
        self.assertEqual(porcelain(self.bdtt), [" D src/b.sql"])
        self.assertFalse((self.bdtt / "src" / "b.sql").exists())
        self.assertEqual(git_text(self.bdtt, "show", "main:src/b.sql"), "select 2;")
        self.assertEqual(self.request(request_id)["promote"]["files"][0]["action"], "delete")

    def test_a_folder_that_lost_its_last_file_goes_too(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/docs/x.md"])
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertFalse((self.bdtt / "docs").exists())
        self.assertTrue((self.bdtt / "src").is_dir())

    def test_a_rename_is_a_create_and_a_delete(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"], outputs={"bdtt_repo/src/c.sql": "select 2;\n"})
        result = self.dry_run(request_id)
        self.assertEqual(sorted((f["path"], f["action"]) for f in result["files"]), [("bdtt_repo/src/b.sql", "delete"), ("bdtt_repo/src/c.sql", "create")])
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual(porcelain(self.bdtt), [" D src/b.sql", "?? src/c.sql"])
        self.assertEqual((self.bdtt / "src" / "c.sql").read_text(encoding="utf-8"), "select 2;\n")

    def test_the_deleted_file_and_the_patch_are_saved_in_dev(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        dev = self.root / TASK / "DEV"
        self.assertEqual((dev / "_deleted" / "bdtt_repo" / "src" / "b.sql").read_text(encoding="utf-8"), "select 2;\n")
        patch = (dev / f"{request_id}.patch").read_text(encoding="utf-8")
        for needle in ("diff --git a/bdtt_repo/src/b.sql", "deleted file", "+++ /dev/null", "-select 2;"):
            self.assertIn(needle, patch)

    def test_main_changed_after_the_file_was_fetched(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        (self.bdtt / "src" / "b.sql").write_text("select 22;\n", encoding="utf-8")
        run_git(self.bdtt, "commit", "-aqm", "change b")
        self.assertIn("变了", self.refused("promote", "--request", request_id, "--dry-run"))

    def test_main_lost_the_file_after_it_was_fetched(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        run_git(self.bdtt, "rm", "-q", "src/b.sql")
        run_git(self.bdtt, "commit", "-qm", "remove b")
        self.assertIn("没有了", self.refused("promote", "--request", request_id, "--dry-run"))

    def test_the_plan_digest_changes_when_a_delete_is_added(self) -> None:
        first = self.delete_flow(["bdtt_repo/src/b.sql"])
        one = self.dry_run(first)["plan_sha256"]
        self.end(first)
        two = self.dry_run(self.delete_flow(["bdtt_repo/src/b.sql"], outputs={"bdtt_repo/src/c.sql": "select 2;\n"}, branch="feature/other"))["plan_sha256"]
        self.assertNotEqual(one, two)


class RecoveryTests(DeleteCase):
    def test_a_deleted_file_is_put_back_with_restore(self) -> None:
        repo = {"path": "/x/bdtt_repo", "base_ref": "main", "current_branch": "main"}
        written = [
            {"relative": "src/b.sql", "action": "delete"},
            {"relative": "src/a.sql", "action": "modify"},
            {"relative": "src/new.sql", "action": "create"},
        ]
        steps = promote_target.recovery_steps(repo, BRANCH, True, written)
        self.assertEqual(steps[0]["git"], ["restore", "--", "src/b.sql", "src/a.sql"])
        self.assertEqual(steps[1]["git"], ["clean", "-f", "--", "src/new.sql"])

    def test_recover_brings_a_deleted_file_back(self) -> None:
        request_id = self.delete_flow(["bdtt_repo/src/b.sql"])
        self.dry_run(request_id)
        self.approve(request_id)
        # a failure after the delete: the same record `partial` would hold
        found = promote_target.ops.load_targets(self.root)
        item = {"relative": "src/b.sql", "action": "delete"}
        repo = {"path": str(self.bdtt), "base_ref": "main", "current_branch": "main", "name": "bdtt_repo"}
        run_git(self.bdtt, "switch", "-c", BRANCH, "main")
        (self.bdtt / "src" / "b.sql").unlink()
        self.assertEqual(porcelain(self.bdtt), [" D src/b.sql"])
        steps = promote_target.recovery_steps(repo, BRANCH, True, [item])
        results = promote_target.run_recovery(steps, BRANCH, found.timeout)
        self.assertTrue(all(r["status"] in ("done", "skipped") for r in results), results)
        self.assertEqual((self.bdtt / "src" / "b.sql").read_text(encoding="utf-8"), "select 2;\n")
        self.assertEqual(self.branches(self.bdtt), ["main"])


if __name__ == "__main__":
    unittest.main()
