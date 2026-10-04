"""promote into target repositories (B10-A3, M4-10): the plan and its checks, the new branch, the DEV backup, a failure halfway.

The repositories are real git repositories made with `git init` in a temporary folder. Without git, these tests are skipped.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import subprocess
import unittest
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from unittest import mock

import support  # noqa: F401  (puts the engine on sys.path)
from modules.request import layout, promote, promote_target
from modules.request.layout import CommandError
from test_request import SESSION
from test_target_inputs import TASK, TargetCase
from test_targets import GIT, run_git

BRANCH = "feature/add_column"


def git_text(path: Path, *arguments: str) -> str:
    return run_git(path, *arguments)


@contextlib.contextmanager
def blocked_from_replacing(path: Path) -> Iterator[None]:
    """Stop git from replacing `path` while the block runs. macOS and Linux: the folder loses its write bit.
    Windows ignores that bit, so the file is held open by another program instead, which is what blocks a replace there."""
    if os.name == "nt":
        held = open(path, "rb")
        try:
            yield
        finally:
            held.close()
    else:
        folder = path.parent
        folder.chmod(0o555)
        try:
            yield
        finally:
            folder.chmod(0o755)


def porcelain(path: Path) -> List[str]:
    """`git status --porcelain` lines, sorted. (run_git strips the first space away.)"""
    done = subprocess.run(["git", "-C", str(path), "status", "--porcelain"], capture_output=True, text=True, check=True)
    return sorted(done.stdout.splitlines())


@unittest.skipUnless(GIT, "git is not installed")
class PromoteCase(TargetCase):
    def flow(
        self,
        outputs: Dict[str, str],
        fetched: Optional[List[str]] = None,
        branch: str = BRANCH,
        task: str = TASK,
    ) -> str:
        """A request with one builder round and a passed reviewer. `outputs`: `<repo>/<path>` -> text. `fetched`: what the builder got from main."""
        request_id = self.target_request(branch=branch, task=task)
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        extra: List[str] = []
        for spec in fetched if fetched is not None else [key for key in outputs if key in ("bdtt_repo/src/a.sql", "b9td_repo/a.sql")]:
            extra += ["--from-target", spec]
        self.run_cli("dispatch", "--request", request_id, "--role", "builder", *extra)
        paths: List[str] = []
        for key, text in outputs.items():
            self.output(request_id, 1, "builder", key, text)
            paths += ["--output", key]
        self.submit(request_id, "builder", "passed", *paths)
        self.reviewer_round(request_id, 1)
        return request_id

    def end(self, request_id: str) -> None:
        """One open request per session: end this one before a test builds another."""
        self.run_cli("request", "set-status", "--request", request_id, "--status", "abandoned", "--reason", "next case")

    def dry_run(self, request_id: str, ok: bool = True) -> Any:
        return self.run_cli("promote", "--request", request_id, "--dry-run", ok=ok)

    def promote_now(self, request_id: str, ok: bool = True) -> Any:
        return self.run_cli("promote", "--request", request_id, ok=ok)

    def branches(self, repo: Path) -> List[str]:
        return git_text(repo, "branch", "--format=%(refname:short)").split()

    def assert_untouched(self, repo: Path) -> None:
        self.assertEqual(self.branches(repo), ["main"])
        self.assertEqual(git_text(repo, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(git_text(repo, "status", "--porcelain"), "")


class PlanTests(PromoteCase):
    def test_dry_run_shows_the_plan_and_changes_nothing(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        before = self.main_commit(self.bdtt)
        result = self.dry_run(request_id)
        self.assertEqual(result["branch"], BRANCH)
        self.assertEqual([(f["path"], f["action"]) for f in result["files"]], [("bdtt_repo/src/a.sql", "modify")])
        self.assertEqual(result["repos"][0]["name"], "bdtt_repo")
        self.assertEqual(result["repos"][0]["base_commit"], before)
        self.assertEqual((result["files"][0]["added"], result["files"][0]["removed"]), (1, 1))
        self.assertIn("approve-promote", result["next"])
        self.assert_untouched(self.bdtt)
        self.assert_untouched(self.b9td)
        self.assertEqual((self.bdtt / "src" / "a.sql").read_text(encoding="utf-8"), "select 1;\n")
        self.assertEqual(self.request(request_id)["promote"]["state"], "dry_run")

    def test_a_new_file_is_a_create(self) -> None:
        request_id = self.flow({"bdtt_repo/src/new.sql": "select 3;\n"}, fetched=[])
        result = self.dry_run(request_id)
        self.assertEqual([(f["path"], f["action"]) for f in result["files"]], [("bdtt_repo/src/new.sql", "create")])

    def test_a_file_the_same_as_main_is_skipped_and_nothing_to_write_is_refused(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1;\n", "bdtt_repo/src/new.sql": "select 3;\n"}, fetched=["bdtt_repo/src/a.sql"])
        result = self.dry_run(request_id)
        self.assertEqual(sorted((f["path"], f["action"]) for f in result["files"]), [("bdtt_repo/src/a.sql", "unchanged"), ("bdtt_repo/src/new.sql", "create")])
        self.end(request_id)
        alone = self.flow({"bdtt_repo/src/a.sql": "select 1;\n"}, branch="feature/other")
        self.assertIn("完全一样", self.refused("promote", "--request", alone, "--dry-run"))

    def test_the_plan_digest_follows_the_content_the_branch_and_main(self) -> None:
        first = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        one = self.dry_run(first)["plan_sha256"]
        self.end(first)
        two = self.dry_run(self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"}, branch="feature/other"))["plan_sha256"]
        self.assertNotEqual(one, two)


class CheckTests(PromoteCase):
    def say(self, request_id: str) -> str:
        return self.refused("promote", "--request", request_id, "--dry-run")

    def test_an_uncommitted_file_in_a_repository_stops_everything(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n", "b9td_repo/a.sql": "select 9, 9;\n"})
        (self.b9td / "scratch.txt").write_text("x\n", encoding="utf-8")
        message = self.say(request_id)
        self.assertIn("b9td_repo：工作区不干净", message)
        self.assertIn("scratch.txt", message)
        self.assertIn("没有写任何东西", message)
        self.assert_untouched(self.bdtt)

    def test_every_problem_is_listed_not_only_the_first(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n", "b9td_repo/a.sql": "select 9, 9;\n"})
        (self.bdtt / "x.txt").write_text("x\n", encoding="utf-8")
        run_git(self.b9td, "branch", BRANCH)
        message = self.say(request_id)
        self.assertIn("bdtt_repo：工作区不干净", message)
        self.assertIn(f"b9td_repo：分支 `{BRANCH}` 已经存在", message)

    def test_main_changed_under_a_file_the_request_took(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        (self.bdtt / "src" / "a.sql").write_text("select 100;\n", encoding="utf-8")
        run_git(self.bdtt, "commit", "-q", "-am", "someone else")
        message = self.say(request_id)
        self.assertIn("在 main 上变了", message)
        self.assertIn("重新取文件", message)

    def test_main_moved_somewhere_else_does_not_matter_and_the_branch_starts_from_the_new_main(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        (self.bdtt / "docs" / "x.md").write_text("changed\n", encoding="utf-8")
        run_git(self.bdtt, "commit", "-q", "-am", "docs")
        result = self.dry_run(request_id)
        self.assertEqual(result["repos"][0]["base_commit"], self.main_commit(self.bdtt))
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual(git_text(self.bdtt, "rev-parse", f"{BRANCH}~0"), self.main_commit(self.bdtt))

    def test_the_main_that_moved_after_the_dry_run_needs_a_new_dry_run(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        (self.bdtt / "docs" / "x.md").write_text("changed\n", encoding="utf-8")
        run_git(self.bdtt, "commit", "-q", "-am", "docs")
        self.assertIn("--dry-run", self.refused("promote", "--request", request_id))
        self.assertEqual(self.branches(self.bdtt), ["main"])

    def test_a_new_file_that_main_has_since_gained_is_refused(self) -> None:
        request_id = self.flow({"bdtt_repo/src/new.sql": "select 3;\n"}, fetched=[])
        (self.bdtt / "src" / "new.sql").write_text("select 4;\n", encoding="utf-8")
        run_git(self.bdtt, "add", "-A")
        run_git(self.bdtt, "commit", "-q", "-m", "someone added it")
        self.assertIn("没有从 main 取过", self.say(request_id))

    def test_an_existing_file_that_was_not_taken_from_main_is_refused(self) -> None:
        request_id = self.flow({"bdtt_repo/src/b.sql": "select 22;\n"}, fetched=[])
        self.assertIn("--from-target bdtt_repo/src/b.sql", self.say(request_id))

    def test_a_file_the_request_took_that_main_lost_is_refused(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        run_git(self.bdtt, "rm", "-q", "src/a.sql")
        run_git(self.bdtt, "commit", "-q", "-m", "removed")
        self.assertIn("现在 main 上没有了", self.say(request_id))

    def test_a_name_that_differs_only_in_letter_case_is_refused(self) -> None:
        request_id = self.flow({"bdtt_repo/src/A.SQL": "select 5;\n"}, fetched=[])
        self.assertIn("只差大小写", self.say(request_id))
        self.end(request_id)
        folder = self.flow({"bdtt_repo/SRC/n.sql": "select 5;\n"}, fetched=[], branch="feature/other")
        self.assertIn("只差大小写", self.say(folder))

    def test_a_file_where_a_folder_is_needed_is_refused(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql/x.sql": "select 5;\n"}, fetched=[])
        self.assertIn("在 main 上是文件", self.say(request_id))

    def test_a_path_that_became_refused_after_the_handoff_is_refused(self) -> None:
        request_id = self.flow({"bdtt_repo/docs/x.md": "doc 2\n"})
        self.override({"repos_root": str(self.repos), "refused_paths+": ["docs/**"]})
        self.assertIn("docs/**", self.say(request_id))

    def test_a_repository_that_is_no_longer_configured_is_refused(self) -> None:
        request_id = self.flow({"b9td_repo/a.sql": "select 9, 9;\n"})
        self.override({"repos": {"bdtt_repo": {"path": str(self.bdtt)}}})
        self.assertIn("不是已配置的目标仓库", self.say(request_id))

    def test_a_branch_name_is_needed(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"}, branch="")
        self.assertIn("还没有分支名", self.say(request_id))
        self.run_cli("request", "set-branch", "--request", request_id, "--branch", "feature/late_name")
        self.assertEqual(self.dry_run(request_id)["branch"], "feature/late_name")

    def test_a_reviewer_that_did_not_pass_is_refused(self) -> None:
        request_id = self.target_request(branch=BRANCH)
        self.attempt(request_id)
        self.assertIn("reviewer 还不是 passed", self.say(request_id))


class RunTests(PromoteCase):
    def test_the_result_lands_on_a_new_branch_and_is_not_committed(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n", "bdtt_repo/src/new.sql": "select 3;\n"}, fetched=["bdtt_repo/src/a.sql"])
        main = self.main_commit(self.bdtt)
        self.dry_run(request_id)
        self.approve(request_id)
        result = self.promote_now(request_id)
        self.assertIn(BRANCH, result["next"])
        self.assertEqual(git_text(self.bdtt, "symbolic-ref", "--short", "HEAD"), BRANCH)
        self.assertEqual(git_text(self.bdtt, "rev-parse", "HEAD"), main)  # no commit
        self.assertEqual(self.main_commit(self.bdtt), main)
        self.assertEqual(porcelain(self.bdtt), [" M src/a.sql", "?? src/new.sql"])
        self.assertEqual((self.bdtt / "src" / "a.sql").read_text(encoding="utf-8"), "select 1, 2;\n")
        self.assertEqual(git_text(self.bdtt, "show", "main:src/a.sql"), "select 1;")
        self.assert_untouched(self.b9td)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["state"], record["branch"]), ("done", BRANCH))
        self.assertEqual(record["repos"]["bdtt_repo"]["base_commit"], main)
        self.assertEqual(sorted(f["path"] for f in record["files"]), ["bdtt_repo/src/a.sql", "bdtt_repo/src/new.sql"])
        self.run_cli("request", "set-status", "--request", request_id, "--status", "accepted")

    def test_two_repositories_go_onto_the_same_branch_name(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n", "b9td_repo/a.sql": "select 9, 9;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        for repo, name in ((self.bdtt, "src/a.sql"), (self.b9td, "a.sql")):
            self.assertEqual(git_text(repo, "symbolic-ref", "--short", "HEAD"), BRANCH)
            self.assertEqual(porcelain(repo), [f" M {name}"])

    def test_the_bytes_are_written_as_they_are(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "x\n"})
        path = self.rd(request_id) / "handoffs" / "orchestrator" / "attempt-001" / "to-reviewer" / "candidate" / "bdtt_repo" / "src" / "a.sql"
        self.assertEqual(path.read_bytes(), b"x\n")
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual((self.bdtt / "src" / "a.sql").read_bytes(), b"x\n")

    def test_the_result_and_a_patch_are_saved_in_the_task_dev_folder(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n", "bdtt_repo/src/new.sql": "select 3;\n"}, fetched=["bdtt_repo/src/a.sql"])
        self.dry_run(request_id)
        self.approve(request_id)
        result = self.promote_now(request_id)
        dev = self.root / TASK / "DEV"
        self.assertEqual((dev / "bdtt_repo" / "src" / "a.sql").read_text(encoding="utf-8"), "select 1, 2;\n")
        self.assertEqual((dev / "bdtt_repo" / "src" / "new.sql").read_text(encoding="utf-8"), "select 3;\n")
        patch = (dev / f"{request_id}.patch").read_text(encoding="utf-8")
        self.assertIn("--- a/bdtt_repo/src/a.sql", patch)
        self.assertIn("-select 1;", patch)
        self.assertIn("+select 1, 2;", patch)
        self.assertIn("+select 3;", patch)
        self.assertIn(f"# repository bdtt_repo: main at {self.main_commit(self.bdtt)}", patch)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["dev"], record["patch"]), (f"{TASK}/DEV", f"{TASK}/DEV/{request_id}.patch"))
        self.assertIn(TASK, result["next"])

    def test_without_a_task_the_backup_is_in_the_request_folder(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"}, task="")
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertTrue((self.rd(request_id) / "DEV" / "bdtt_repo" / "src" / "a.sql").is_file())
        self.assertTrue((self.rd(request_id) / "DEV" / f"{request_id}.patch").is_file())

    def test_it_is_done_once(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertIn("已经 promote 过了", self.refused("promote", "--request", request_id))

    def test_no_approval_no_write(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        self.assertIn("--dry-run", self.refused("promote", "--request", request_id))
        self.dry_run(request_id)
        self.assertIn("还没有批准", self.refused("promote", "--request", request_id))
        self.assert_untouched(self.bdtt)

    def test_the_approval_screen_names_the_repository_and_the_branch(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        plan = self.request(request_id)["promote"]["plan_sha256"]
        out = io.StringIO()
        promote.approve(self.root, request_id, reader=lambda _prompt: plan[:8], interactive=True, out=out)
        shown = out.getvalue()
        self.assertIn("仓库 bdtt_repo", shown)
        self.assertIn(f"新建分支 {BRANCH}", shown)
        self.assertIn("modify", shown)

    def test_a_repository_that_became_dirty_after_the_approval_is_not_written(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n", "b9td_repo/a.sql": "select 9, 9;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        (self.b9td / "scratch.txt").write_text("x\n", encoding="utf-8")
        self.assertIn("工作区不干净", self.refused("promote", "--request", request_id))
        self.assert_untouched(self.bdtt)

    def test_a_backup_that_cannot_be_written_stops_before_any_repository_is_touched(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        (self.root / TASK / "DEV").write_text("a file where the folder should be\n", encoding="utf-8")
        self.dry_run(request_id)
        self.approve(request_id)
        self.assertIn("仓库一个都没有改", self.refused("promote", "--request", request_id))
        self.assert_untouched(self.bdtt)
        self.assertEqual(self.request(request_id)["promote"]["state"], "dry_run")  # still approved: fix the folder and run again
        (self.root / TASK / "DEV").unlink()
        self.promote_now(request_id)

    def test_the_report_says_where_the_backup_is(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.run_cli("request", "set-status", "--request", request_id, "--status", "accepted")
        report = (self.root / ".workspace" / "reports" / f"{request_id}.md").read_text(encoding="utf-8")
        self.assertIn(f"{TASK}/DEV", report)


class FailureBase(PromoteCase):
    """The repositories are written in name order: b9td_repo first, then bdtt_repo."""

    def two_repo_request(self) -> str:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n", "b9td_repo/a.sql": "select 9, 9;\n"})
        self.dry_run(request_id)
        self.approve(request_id)
        return request_id

    def fail_on(self, file: Path):
        """Writing `file` in a repository fails (the backup copy of the same name is not hit)."""
        real = promote_target.ops.copy_file

        def copy(source: Path, destination: Path) -> None:
            if Path(destination) == file:
                raise OSError("disk full (test)")
            real(source, destination)

        return mock.patch.object(promote_target.ops, "copy_file", copy)

    def run_commands(self, commands: List[str]) -> None:
        for command in commands:
            subprocess.run(shlex.split(command), check=True, capture_output=True)


class FailureTests(FailureBase):
    def test_a_failure_in_the_second_repository_is_reported_and_recoverable(self) -> None:
        request_id = self.two_repo_request()
        with self.fail_on(self.bdtt / "src" / "a.sql"):
            with self.assertRaises(CommandError) as raised:
                promote.run(self.root, request_id, False)
        message = str(raised.exception)
        self.assertIn("出错的仓库：bdtt_repo", message)
        self.assertIn("disk full (test)", message)
        self.assertIn("已经写好的仓库（在新分支 " + BRANCH + " 上，文件没有提交）：b9td_repo", message)
        self.assertIn("没有动过的仓库：（没有）", message)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["state"], record["repos_done"], record["repo_failed"], record["repos_untouched"]), ("partial", ["b9td_repo"], "bdtt_repo", []))
        self.assertTrue((self.root / TASK / "DEV" / "bdtt_repo" / "src" / "a.sql").is_file())  # the backup was made before any write
        self.assertEqual(git_text(self.b9td, "symbolic-ref", "--short", "HEAD"), BRANCH)
        self.assertEqual(git_text(self.bdtt, "symbolic-ref", "--short", "HEAD"), BRANCH)  # switched, then the write failed
        for line in record["recovery"]:
            self.assertIn(" -C ", line)
            self.assertIn(line, message)
        self.run_commands(record["recovery"])
        self.assert_untouched(self.bdtt)
        self.assert_untouched(self.b9td)
        self.assertEqual((self.b9td / "a.sql").read_text(encoding="utf-8"), "select 9;\n")

    def test_after_a_failure_promote_waits_for_a_new_dry_run_and_a_new_approval(self) -> None:
        request_id = self.two_repo_request()
        with self.fail_on(self.bdtt / "src" / "a.sql"):
            with self.assertRaises(CommandError):
                promote.run(self.root, request_id, False)
        self.assertIn("中途出错", self.refused("promote", "--request", request_id))
        self.assertIn("promote.recovery", self.refused("promote", "--request", request_id, "--dry-run"))  # not recovered yet: the branch exists
        self.assertIn("还没有 promote", self.refused("request", "set-status", "--request", request_id, "--status", "accepted"))
        self.run_commands(self.request(request_id)["promote"]["recovery"])
        self.dry_run(request_id)
        self.assertIn("还没有批准", self.refused("promote", "--request", request_id))
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual(self.request(request_id)["promote"]["state"], "done")
        self.assertEqual(porcelain(self.b9td), [" M a.sql"])
        self.assertEqual(porcelain(self.bdtt), [" M src/a.sql"])

    def test_a_failure_in_the_first_repository_leaves_the_second_untouched(self) -> None:
        request_id = self.two_repo_request()
        with self.fail_on(self.b9td / "a.sql"):
            with self.assertRaises(CommandError) as raised:
                promote.run(self.root, request_id, False)
        self.assertIn("没有动过的仓库：bdtt_repo", str(raised.exception))
        self.assert_untouched(self.bdtt)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["repos_done"], record["repo_failed"], record["repos_untouched"]), ([], "b9td_repo", ["bdtt_repo"]))
        self.run_commands(record["recovery"])
        self.assert_untouched(self.b9td)

    def test_a_branch_that_cannot_be_made_is_reported_and_the_earlier_repository_is_recoverable(self) -> None:
        request_id = self.two_repo_request()
        real = promote_target.targets.git

        def git(repo: Any, *arguments: str, **keywords: Any) -> bytes:
            if arguments[:1] == ("switch",) and repo.name == "bdtt_repo":
                raise promote_target.targets.TargetError("git switch failed (test)")
            return real(repo, *arguments, **keywords)

        with mock.patch.object(promote_target.targets, "git", git):
            with self.assertRaises(CommandError) as raised:
                promote.run(self.root, request_id, False)
        self.assertIn("git switch failed (test)", str(raised.exception))
        self.assert_untouched(self.bdtt)
        record = self.request(request_id)["promote"]
        self.assertEqual((record["repos_done"], record["repo_failed"]), (["b9td_repo"], "bdtt_repo"))
        self.assertTrue(all("b9td_repo" in line for line in record["recovery"]))  # nothing to undo in the repository whose switch failed
        self.run_commands(record["recovery"])
        self.assert_untouched(self.b9td)

    def test_the_recovery_commands_quote_paths_with_spaces(self) -> None:
        repo = {"path": "/tmp/my repos/a", "current_branch": "main", "base_ref": "main"}
        commands = promote_target.recovery_commands(repo, BRANCH, True, [{"action": "modify", "relative": "src/a b.sql"}, {"action": "create", "relative": "n.sql"}])
        self.assertEqual(commands, [
            'git -C "/tmp/my repos/a" restore -- "src/a b.sql"',
            'git -C "/tmp/my repos/a" clean -f -- "n.sql"',
            'git -C "/tmp/my repos/a" switch "main"',
            f'git -C "/tmp/my repos/a" branch -d "{BRANCH}"',
        ])
        detached = promote_target.recovery_commands({**repo, "current_branch": "(detached)"}, BRANCH, True, [])
        self.assertEqual(detached[0], 'git -C "/tmp/my repos/a" switch "main"')


class RecoverTests(FailureBase):
    """`request recover`: the person puts the repositories back with one command (the steps are the recorded ones)."""

    def partial_request(self) -> str:
        request_id = self.two_repo_request()
        with self.fail_on(self.bdtt / "src" / "a.sql"):
            with self.assertRaises(CommandError):
                promote.run(self.root, request_id, False)
        return request_id

    def recover(self, request_id: str, code: Optional[str] = None) -> Dict[str, Any]:
        plan = self.request(request_id)["promote"]["plan_sha256"]
        out = io.StringIO()
        self.shown = out
        return promote.recover(self.root, request_id, reader=lambda _prompt: code if code is not None else plan[:8], interactive=True, out=out)

    def test_the_message_names_the_command_and_the_record_has_the_steps(self) -> None:
        request_id = self.two_repo_request()
        with self.fail_on(self.bdtt / "src" / "a.sql"):
            with self.assertRaises(CommandError) as raised:
                promote.run(self.root, request_id, False)
        self.assertIn(f"request recover --request {request_id}", str(raised.exception))
        record = self.request(request_id)["promote"]
        self.assertEqual(len(record["recovery_steps"]), len(record["recovery"]))
        self.assertEqual(record["recovery_steps"][0], {"repo": str(self.b9td), "git": ["restore", "--", "a.sql"]})
        self.assertEqual(record["request_id"], request_id)

    def test_recover_puts_both_repositories_back_and_opens_the_promote_again(self) -> None:
        request_id = self.partial_request()
        result = self.recover(request_id)
        self.assertTrue(result["recovered"])
        self.assertEqual((result["done"], result["skipped"]), (6, 0))
        self.assertIn("restore", self.shown.getvalue())
        self.assert_untouched(self.bdtt)
        self.assert_untouched(self.b9td)
        record = self.request(request_id)["promote"]
        self.assertEqual(record["state"], "none")
        self.assertIn("recovered_at", record)
        self.dry_run(request_id)
        self.approve(request_id)
        self.promote_now(request_id)
        self.assertEqual(self.request(request_id)["promote"]["state"], "done")

    def test_recover_without_an_id_finds_the_one_request(self) -> None:
        request_id = self.partial_request()
        plan = self.request(request_id)["promote"]["plan_sha256"]
        promote.recover(self.root, "", reader=lambda _prompt: plan[:8], interactive=True, out=io.StringIO())
        self.assert_untouched(self.b9td)

    def test_only_a_person_at_a_terminal_can_recover(self) -> None:
        request_id = self.partial_request()
        self.assertIn("只能由用户在自己的终端", self.refused("request", "recover", "--request", request_id))
        self.assertEqual(git_text(self.b9td, "symbolic-ref", "--short", "HEAD"), BRANCH)  # nothing was done

    def test_a_wrong_code_does_nothing(self) -> None:
        request_id = self.partial_request()
        with self.assertRaises(CommandError) as raised:
            self.recover(request_id, code="nope")
        self.assertIn("什么都没有做", str(raised.exception))
        self.assertEqual(git_text(self.b9td, "symbolic-ref", "--short", "HEAD"), BRANCH)
        self.assertEqual(self.request(request_id)["promote"]["state"], "partial")

    def test_a_record_without_steps_is_not_run_blind(self) -> None:
        request_id = self.partial_request()
        path = self.rd(request_id) / "request.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["promote"]["recovery_steps"]  # a record from before the steps were kept
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CommandError) as raised:
            self.recover(request_id)
        self.assertIn("promote.recovery", str(raised.exception))
        self.assertEqual(git_text(self.b9td, "symbolic-ref", "--short", "HEAD"), BRANCH)

    def test_it_is_for_a_promote_that_stopped_halfway(self) -> None:
        request_id = self.two_repo_request()
        with self.assertRaises(CommandError) as raised:
            self.recover(request_id)
        self.assertIn("不需要恢复", str(raised.exception))
        with self.assertRaises(CommandError) as raised:
            promote.recover(self.root, "", reader=lambda _p: "x", interactive=True, out=io.StringIO())
        self.assertIn("没有中途出错的 promote", str(raised.exception))

    def test_a_step_that_fails_stops_that_repository_only_and_a_second_run_finishes(self) -> None:
        request_id = self.partial_request()
        (self.bdtt / "src" / "a.sql").write_text("half written\n", encoding="utf-8")  # a change that git has to undo
        with blocked_from_replacing(self.bdtt / "src" / "a.sql"):
            with self.assertRaises(CommandError) as raised:
                self.recover(request_id)
            self.assertIn("没有成功", str(raised.exception))
            self.assertIn("[failed]", self.shown.getvalue())
            self.assert_untouched(self.b9td)  # the other repository is back
            self.assertEqual(git_text(self.bdtt, "symbolic-ref", "--short", "HEAD"), BRANCH)  # this one stopped at its first step
            self.assertEqual(self.request(request_id)["promote"]["state"], "partial")
        self.recover(request_id)  # the finished repository's steps are skipped, the rest runs
        self.assertIn("[skipped]", self.shown.getvalue())
        self.assert_untouched(self.bdtt)
        self.assertEqual(self.request(request_id)["promote"]["state"], "none")

    def test_a_repository_the_person_already_switched_back_keeps_its_files(self) -> None:
        request_id = self.partial_request()
        run_git(self.b9td, "switch", "main")  # the written change comes along: it is now the person's
        self.recover(request_id)
        self.assertEqual(porcelain(self.b9td), [" M a.sql"])
        self.assertEqual(self.branches(self.b9td), ["main"])  # the empty promote branch is gone
        self.assert_untouched(self.bdtt)


class SetBranchTests(PromoteCase):
    def test_a_new_branch_name_after_a_dry_run_drops_the_plan(self) -> None:
        request_id = self.flow({"bdtt_repo/src/a.sql": "select 1, 2;\n"})
        self.dry_run(request_id)
        self.assertTrue(self.run_cli("request", "set-branch", "--request", request_id, "--branch", "feature/other")["promote_plan_reset"])
        self.assertEqual(self.dry_run(request_id)["branch"], "feature/other")


if __name__ == "__main__":
    unittest.main()
