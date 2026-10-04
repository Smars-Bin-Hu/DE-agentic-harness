"""Requests with target repositories (B10-A2, M4-10): task and branch, files read from the base branch, output paths.

The repositories are real git repositories made with `git init` in a temporary folder. Without git, these tests are skipped.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

import support  # noqa: F401  (puts the engine on sys.path)
from core import targets
from modules.request import handler
from test_request import SESSION, RequestCase
from test_targets import GIT, SYMLINKS, make_repo, run_git

TASK = ".workspace/current_tasks/job1"
CRLF = b"select 1;\r\nselect 2;\r\n"
BINARY = bytes(range(256))


@unittest.skipUnless(GIT, "git is not installed")
class TargetCase(RequestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repos = self.root / "source" / "repos"
        self.bdtt = make_repo(self.repos / "bdtt_repo", {"src/a.sql": "select 1;\n", "src/b.sql": "select 2;\n", "docs/x.md": "doc\n"})
        self.b9td = make_repo(self.repos / "b9td_repo", {"a.sql": "select 9;\n"})
        self.override({"repos_root": str(self.repos)})
        (self.root / TASK).mkdir(parents=True)

    def override(self, data: dict) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps(data), encoding="utf-8")

    def target_request(self, branch: str = "", task: str = TASK) -> str:
        extra = (["--task", task] if task else []) + (["--branch", branch] if branch else [])
        return self.run_cli("request", "new", "--title", "Add column", "--session-id", SESSION, *extra)["request_id"]

    def inputs(self, request_id: str) -> Path:
        return self.rd(request_id) / "handoffs" / "orchestrator" / "init-inputs"

    def main_commit(self, repo: Path) -> str:
        return run_git(repo, "rev-parse", "main")

    def blob(self, repo: Path, path: str) -> str:
        return run_git(repo, "rev-parse", f"main:{path}")

    def add(self, request_id: str, *specs: str, ok: bool = True) -> Any:
        extra = []
        for item in specs:
            extra += ["--from-target", item]
        return self.run_cli("request", "add-input", "--request", request_id, *extra, ok=ok)


class NewRequestTests(TargetCase):
    def test_a_request_records_task_branch_and_that_it_has_targets(self) -> None:
        result = self.run_cli("request", "new", "--title", "Add column", "--session-id", SESSION, "--task", TASK, "--branch", "feature/your_custom_feature_name_like_this")
        data = self.request(result["request_id"])
        self.assertEqual((data["task"], data["branch"], data["target_mode"]), (TASK, "feature/your_custom_feature_name_like_this", True))
        self.assertEqual(data["targets"], {})
        self.assertEqual(result["target_repos"], ["b9td_repo", "bdtt_repo"])
        self.assertIn("--from-target", result["next"])

    def test_task_and_branch_are_optional_and_an_absolute_task_path_is_accepted(self) -> None:
        first = self.target_request(task="")
        data = self.request(first)
        self.assertEqual((data["task"], data["branch"], data["target_mode"]), ("", "", True))
        self.run_cli("request", "set-status", "--request", first, "--status", "abandoned", "--reason", "x")
        data = self.request(self.target_request(task=str(self.root / TASK)))
        self.assertEqual(data["task"], TASK)

    def test_without_target_repositories_the_request_is_as_before(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        request_id = self.new_request()
        self.assertFalse(self.request(request_id)["target_mode"])
        self.assertIn("--branch 用不上", self.refused("request", "new", "--title", "t2", "--session-id", SESSION, "--branch", "feature/x"))

    def test_a_task_must_be_a_folder_under_current_tasks(self) -> None:
        for task in (".workspace/sandbox", "src", "/tmp", ".workspace/current_tasks"):
            with self.subTest(task):
                self.assertIn(".workspace/current_tasks/", self.refused("request", "new", "--title", "t", "--session-id", SESSION, "--task", task))
        self.assertIn("不存在", self.refused("request", "new", "--title", "t", "--session-id", SESSION, "--task", ".workspace/current_tasks/missing"))

    def test_branch_names(self) -> None:
        for name in ("feature/a-b", "feature/a.b", "feature/a/b", "fix/x", "feature/", "feature/ü", "Feature/x", "feature/x y", "feature/" + "a" * 61):
            with self.subTest(name):
                self.assertIn("分支名", self.refused("request", "new", "--title", "t", "--session-id", SESSION, "--branch", name))
        for name in ("feature/Abc_9", "feature/your_custom_feature_name_like_this", "feature/" + "a" * 60):
            with self.subTest(name):
                request_id = self.target_request(branch=name)
                self.assertEqual(self.request(request_id)["branch"], name)
                self.run_cli("request", "set-status", "--request", request_id, "--status", "abandoned", "--reason", "test")

    def test_set_branch(self) -> None:
        request_id = self.target_request()
        result = self.run_cli("request", "set-branch", "--request", request_id, "--branch", "feature/one")
        self.assertEqual((result["branch"], result["promote_plan_reset"]), ("feature/one", False))
        self.assertEqual(self.request(request_id)["branch"], "feature/one")
        self.assertIn("分支名", self.refused("request", "set-branch", "--request", request_id, "--branch", "feature/a-b"))

    def test_a_new_branch_name_drops_a_dry_run_and_its_approval(self) -> None:
        request_id = self.target_request(branch="feature/one")
        path = self.rd(request_id) / "request.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["promote"] = {"state": "dry_run", "plan_sha256": "abc", "approved_plan_sha256": "abc", "approved_at": "x"}
        path.write_text(json.dumps(data), encoding="utf-8")
        result = self.run_cli("request", "set-branch", "--request", request_id, "--branch", "feature/two")
        self.assertTrue(result["promote_plan_reset"])
        self.assertEqual(self.request(request_id)["promote"], {"state": "none"})

    def test_set_branch_is_for_requests_with_targets_that_are_not_done(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        plain = self.new_request("plain")
        self.assertIn("没有目标仓库", self.refused("request", "set-branch", "--request", plain, "--branch", "feature/x"))
        self.run_cli("request", "set-status", "--request", plain, "--status", "abandoned", "--reason", "x")
        self.override({"repos_root": str(self.repos)})
        request_id = self.target_request(branch="feature/x")
        self.run_cli("request", "set-status", "--request", request_id, "--status", "abandoned", "--reason", "x")
        self.assertIn("已经结束", self.refused("request", "set-branch", "--request", request_id, "--branch", "feature/y"))


class AddInputTests(TargetCase):
    def test_a_file_is_copied_as_the_base_branch_has_it(self) -> None:
        request_id = self.target_request()
        result = self.add(request_id, "bdtt_repo/src/a.sql")
        self.assertEqual(result["added"], ["bdtt_repo/src/a.sql"])
        self.assertEqual((self.inputs(request_id) / "bdtt_repo" / "src" / "a.sql").read_bytes(), b"select 1;\n")
        data = self.request(request_id)
        item = data["inputs"][0]
        self.assertEqual((item["repo"], item["source"]), ("bdtt_repo", "bdtt_repo/src/a.sql"))
        self.assertEqual(item["blob"], self.blob(self.bdtt, "src/a.sql"))
        self.assertEqual(item["base_commit"], self.main_commit(self.bdtt))
        self.assertEqual(data["targets"]["bdtt_repo"], {"path": str(self.bdtt), "base_ref": "main", "base_commit": self.main_commit(self.bdtt)})
        self.assertEqual(data["target_files"]["bdtt_repo/src/a.sql"], {"blob": self.blob(self.bdtt, "src/a.sql"), "base_commit": self.main_commit(self.bdtt)})

    def test_the_working_tree_and_the_current_branch_do_not_matter(self) -> None:
        (self.bdtt / "src" / "a.sql").write_text("changed, not committed\n", encoding="utf-8")
        run_git(self.bdtt, "switch", "-q", "-c", "other")
        (self.bdtt / "src" / "b.sql").write_text("other branch\n", encoding="utf-8")
        run_git(self.bdtt, "commit", "-q", "-am", "other")
        request_id = self.target_request()
        self.add(request_id, "bdtt_repo/src/a.sql", "bdtt_repo/src/b.sql")
        self.assertEqual((self.inputs(request_id) / "bdtt_repo" / "src" / "a.sql").read_bytes(), b"select 1;\n")
        self.assertEqual((self.inputs(request_id) / "bdtt_repo" / "src" / "b.sql").read_bytes(), b"select 2;\n")
        self.assertEqual(self.bdtt.joinpath("src", "a.sql").read_text(encoding="utf-8"), "changed, not committed\n")  # nothing was touched

    def test_a_folder_gives_the_tracked_files_under_it_only(self) -> None:
        (self.bdtt / "src" / "untracked.sql").write_text("x\n", encoding="utf-8")
        request_id = self.target_request()
        result = self.add(request_id, "bdtt_repo/src")
        self.assertEqual(sorted(result["added"]), ["bdtt_repo/src/a.sql", "bdtt_repo/src/b.sql"])

    def test_bytes_are_kept_exactly(self) -> None:
        (self.bdtt / "src" / "crlf.sql").write_bytes(CRLF)
        (self.bdtt / "src" / "data.bin").write_bytes(BINARY)
        run_git(self.bdtt, "-c", "core.autocrlf=false", "add", "-A")
        run_git(self.bdtt, "commit", "-q", "-m", "more")
        request_id = self.target_request()
        self.add(request_id, "bdtt_repo/src/crlf.sql", "bdtt_repo/src/data.bin")
        self.assertEqual((self.inputs(request_id) / "bdtt_repo" / "src" / "crlf.sql").read_bytes(), CRLF)
        self.assertEqual((self.inputs(request_id) / "bdtt_repo" / "src" / "data.bin").read_bytes(), BINARY)

    def test_two_repositories_in_one_request(self) -> None:
        request_id = self.target_request()
        self.add(request_id, "bdtt_repo/src/a.sql", "b9td_repo/a.sql")
        data = self.request(request_id)
        self.assertEqual(sorted(data["targets"]), ["b9td_repo", "bdtt_repo"])
        self.assertTrue((self.inputs(request_id) / "b9td_repo" / "a.sql").is_file())

    def test_a_plain_file_and_a_target_file_in_one_command(self) -> None:
        self.write("notes/req.md", "requirement\n")
        request_id = self.target_request()
        self.run_cli("request", "add-input", "--request", request_id, "notes/req.md", "--from-target", "bdtt_repo/src/a.sql")
        self.assertEqual(sorted(item["path"] for item in self.request(request_id)["inputs"]), ["bdtt_repo/src/a.sql", "notes/req.md"])

    def test_a_backslash_path_is_accepted(self) -> None:
        request_id = self.target_request()
        self.add(request_id, "bdtt_repo\\src\\a.sql")
        self.assertTrue((self.inputs(request_id) / "bdtt_repo" / "src" / "a.sql").is_file())

    def test_the_commit_is_fixed_at_the_first_read(self) -> None:
        request_id = self.target_request()
        self.add(request_id, "bdtt_repo/src/a.sql")
        first = self.main_commit(self.bdtt)
        (self.bdtt / "src" / "c.sql").write_text("select 3;\n", encoding="utf-8")
        (self.bdtt / "src" / "a.sql").write_text("select 100;\n", encoding="utf-8")
        run_git(self.bdtt, "add", "-A")
        run_git(self.bdtt, "commit", "-q", "-m", "main moved")
        self.add(request_id, "bdtt_repo/src/b.sql")
        data = self.request(request_id)
        self.assertEqual(data["targets"]["bdtt_repo"]["base_commit"], first)
        self.assertIn("没有", self.add(request_id, "bdtt_repo/src/c.sql", ok=False)["stderr"])  # c.sql is not in the fixed commit
        self.add(request_id, "bdtt_repo/src/a.sql")  # same blob as before, from the fixed commit
        self.assertEqual((self.inputs(request_id) / "bdtt_repo" / "src" / "a.sql").read_bytes(), b"select 1;\n")

    def test_refusals_say_what_to_do(self) -> None:
        request_id = self.target_request()
        cases = {
            "bdtt_repo/src/missing.sql": "没有 `src/missing.sql`",
            "nope/a.sql": "已知的仓库：b9td_repo、bdtt_repo",
            "bdtt_repo": "<仓库名>/<仓库里的路径>",
            "bdtt_repo/": "<仓库名>/<仓库里的路径>",
            "bdtt_repo/../a.sql": "不能指向目录之外",
            "bdtt_repo/C:/x": "必须是相对路径",
        }
        for spec, expected in cases.items():
            with self.subTest(spec):
                self.assertIn(expected, self.add(request_id, spec, ok=False)["stderr"])
        self.assertEqual(self.request(request_id)["inputs"], [])
        self.assertEqual(self.request(request_id)["targets"], {})

    def test_a_missing_base_branch_is_said(self) -> None:
        self.override({"repos_root": str(self.repos), "repos": {"bdtt_repo": {"base_ref": "develop"}}})
        request_id = self.target_request()
        self.assertIn("没有分支 `develop`", self.add(request_id, "bdtt_repo/src/a.sql", ok=False)["stderr"])

    def test_nothing_to_add_and_nothing_configured(self) -> None:
        request_id = self.target_request()
        self.assertIn("--from-target", self.refused("request", "add-input", "--request", request_id))
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        self.assertIn("还没有配置目标仓库", self.add(request_id, "bdtt_repo/src/a.sql", ok=False)["stderr"])

    def test_too_many_files_are_refused(self) -> None:
        path = self.root / ".harness" / "policies" / "orchestration.override.json"
        path.write_text(json.dumps({"inputs": {"max_files": 1}}), encoding="utf-8")
        request_id = self.target_request()
        self.assertIn("上限 1", self.add(request_id, "bdtt_repo/src", ok=False)["stderr"])
        self.assertEqual(self.request(request_id)["target_files"], {})

    @unittest.skipUnless(SYMLINKS, "this account cannot make symlinks (on Windows: turn on Developer Mode or run as admin)")
    def test_a_symbolic_link_in_a_folder_is_skipped_and_asked_for_by_name_is_refused(self) -> None:
        (self.bdtt / "src" / "link.sql").symlink_to("a.sql")
        run_git(self.bdtt, "add", "-A")
        run_git(self.bdtt, "commit", "-q", "-m", "link")
        request_id = self.target_request()
        self.assertEqual(sorted(self.add(request_id, "bdtt_repo/src")["added"]), ["bdtt_repo/src/a.sql", "bdtt_repo/src/b.sql"])
        self.assertIn("不是普通文件", self.add(request_id, "bdtt_repo/src/link.sql", ok=False)["stderr"])

    def test_no_more_input_after_dispatch(self) -> None:
        request_id = self.target_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.dispatch(request_id, "builder")
        self.assertIn("已经派发过", self.add(request_id, "bdtt_repo/src/a.sql", ok=False)["stderr"])

    def test_the_target_repositories_are_not_changed(self) -> None:
        before = {path: (run_git(path, "status", "--porcelain"), run_git(path, "reflog")) for path in (self.bdtt, self.b9td)}
        request_id = self.target_request()
        self.add(request_id, "bdtt_repo/src", "b9td_repo/a.sql")
        after = {path: (run_git(path, "status", "--porcelain"), run_git(path, "reflog")) for path in (self.bdtt, self.b9td)}
        self.assertEqual(before, after)


class DispatchTests(TargetCase):
    def test_dispatch_copies_from_the_target_into_the_package_and_the_manifest_says_where_from(self) -> None:
        request_id = self.target_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        result = self.run_cli("dispatch", "--request", request_id, "--role", "builder", "--from-target", "bdtt_repo/src/a.sql", "--from-target", "b9td_repo/a.sql")
        self.assertEqual(result["files"], 2)
        package = self.rd(request_id) / "handoffs" / "orchestrator" / "attempt-001" / "to-builder"
        self.assertEqual((package / "inputs" / "bdtt_repo" / "src" / "a.sql").read_bytes(), b"select 1;\n")
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        item = next(file for file in manifest["files"] if file["repo"] == "bdtt_repo")
        self.assertEqual((item["path"], item["source"], item["blob"], item["base_commit"]), ("inputs/bdtt_repo/src/a.sql", "bdtt_repo/src/a.sql", self.blob(self.bdtt, "src/a.sql"), self.main_commit(self.bdtt)))
        self.assertFalse((package / "inputs" / "bdtt_repo" / "src" / "a.sql").stat().st_mode & 0o222)  # frozen
        self.assertEqual(self.request(request_id)["target_files"]["b9td_repo/a.sql"]["blob"], self.blob(self.b9td, "a.sql"))
        self.assertTrue(self.check(request_id)["ok"])

    def test_a_failed_dispatch_leaves_nothing_behind(self) -> None:
        request_id = self.target_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.run_cli("dispatch", "--request", request_id, "--role", "builder", "--from-target", "bdtt_repo/src/missing.sql", ok=False)
        data = self.request(request_id)
        self.assertEqual((data["attempts"][0]["dispatched"], data["target_files"], data["targets"]), ({}, {}, {}))
        self.run_cli("dispatch", "--request", request_id, "--role", "builder", "--from-target", "bdtt_repo/src/a.sql")


class StagedFilesTests(TargetCase):
    def package(self, request_id: str, role: str) -> Path:
        return self.rd(request_id) / "handoffs" / "orchestrator" / "attempt-001" / f"to-{role}"

    def manifest(self, request_id: str, role: str) -> Dict[str, Any]:
        return json.loads((self.package(request_id, role) / "manifest.json").read_text(encoding="utf-8"))

    def staged_request(self) -> str:
        request_id = self.target_request(branch="feature/x")
        self.add(request_id, "bdtt_repo/src/a.sql", "b9td_repo/a.sql")
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        return request_id

    def test_the_builder_gets_the_staged_files_without_asking_for_them_again(self) -> None:
        request_id = self.staged_request()
        result = self.run_cli("dispatch", "--request", request_id, "--role", "builder")
        self.assertEqual(result["files"], 2)
        package = self.package(request_id, "builder")
        self.assertEqual((package / "inputs" / "bdtt_repo" / "src" / "a.sql").read_bytes(), b"select 1;\n")
        files = {item["source"]: item for item in self.manifest(request_id, "builder")["files"]}
        self.assertEqual(sorted(files), ["b9td_repo/a.sql", "bdtt_repo/src/a.sql"])
        self.assertEqual(files["bdtt_repo/src/a.sql"]["blob"], self.blob(self.bdtt, "src/a.sql"))
        self.assertFalse((package / "inputs" / "bdtt_repo" / "src" / "a.sql").stat().st_mode & 0o222)
        self.assertTrue(self.check(request_id)["ok"])

    def test_the_staged_files_are_what_was_staged_even_if_main_moved(self) -> None:
        request_id = self.staged_request()
        (self.bdtt / "src" / "a.sql").write_text("select 100;\n", encoding="utf-8")
        run_git(self.bdtt, "commit", "-q", "-am", "moved")
        self.run_cli("dispatch", "--request", request_id, "--role", "builder")
        self.assertEqual((self.package(request_id, "builder") / "inputs" / "bdtt_repo" / "src" / "a.sql").read_bytes(), b"select 1;\n")

    def test_a_file_named_again_in_dispatch_is_not_copied_twice(self) -> None:
        request_id = self.staged_request()
        result = self.run_cli("dispatch", "--request", request_id, "--role", "builder", "--from-target", "bdtt_repo/src/a.sql")
        self.assertEqual(result["files"], 2)
        self.assertEqual(len(self.manifest(request_id, "builder")["files"]), 2)

    def test_nothing_is_added_when_nothing_was_staged(self) -> None:
        request_id = self.target_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.assertEqual(self.run_cli("dispatch", "--request", request_id, "--role", "builder")["files"], 0)

    def test_too_many_staged_files_are_refused_at_dispatch(self) -> None:
        request_id = self.staged_request()
        (self.root / ".harness" / "policies" / "orchestration.override.json").write_text(json.dumps({"inputs": {"max_files": 1}}), encoding="utf-8")
        self.assertIn("上限", self.run_cli("dispatch", "--request", request_id, "--role", "builder", ok=False)["stderr"])
        self.assertEqual(self.request(request_id)["attempts"][0]["dispatched"], {})

    def test_the_reviewer_gets_the_main_version_of_each_changed_file_and_nothing_for_a_new_file(self) -> None:
        request_id = self.staged_request()
        self.run_cli("dispatch", "--request", request_id, "--role", "builder")
        self.output(request_id, 1, "builder", "bdtt_repo/src/a.sql", "select 1, 2;\n")
        self.output(request_id, 1, "builder", "bdtt_repo/src/new.sql", "select 3;\n")
        self.submit(request_id, "builder", "passed", "--output", "bdtt_repo/src/a.sql", "--output", "bdtt_repo/src/new.sql")
        self.fill_assignment(request_id, 1, "reviewer")
        self.dispatch(request_id, "reviewer")
        package = self.package(request_id, "reviewer")
        self.assertEqual((package / "base" / "bdtt_repo" / "src" / "a.sql").read_bytes(), b"select 1;\n")
        self.assertFalse((package / "base" / "bdtt_repo" / "src" / "new.sql").exists())
        self.assertEqual((package / "candidate" / "bdtt_repo" / "src" / "new.sql").read_text(encoding="utf-8"), "select 3;\n")
        purposes = {item["path"] + ":" + item["purpose"] for item in self.manifest(request_id, "reviewer")["files"]}
        self.assertIn("base/bdtt_repo/src/a.sql:base", purposes)
        self.assertIn("candidate/bdtt_repo/src/a.sql:candidate", purposes)
        self.assertTrue(self.check(request_id)["ok"])

    def test_the_reviewer_gets_a_diff_against_main_and_is_told_to_read_it_first(self) -> None:
        request_id = self.staged_request()
        self.run_cli("dispatch", "--request", request_id, "--role", "builder")
        self.output(request_id, 1, "builder", "bdtt_repo/src/a.sql", "select 1;\nselect 2;\n")
        self.output(request_id, 1, "builder", "bdtt_repo/src/new.sql", "select 3;\n")
        self.submit(request_id, "builder", "passed", "--output", "bdtt_repo/src/a.sql", "--output", "bdtt_repo/src/new.sql")
        self.fill_assignment(request_id, 1, "reviewer")
        self.dispatch(request_id, "reviewer")
        package = self.package(request_id, "reviewer")
        diff = (package / "candidate.diff").read_text(encoding="utf-8")
        self.assertIn("diff --git a/bdtt_repo/src/a.sql b/bdtt_repo/src/a.sql", diff)
        self.assertIn("--- a/bdtt_repo/src/a.sql", diff)
        self.assertIn("+select 2;", diff)
        self.assertNotIn("+select 1;", diff)  # an unchanged line is context, not a change
        self.assertIn("--- /dev/null\n+++ b/bdtt_repo/src/new.sql\n+select 3;", diff)  # a new file is all additions
        self.assertTrue((package / "candidate.diff").stat().st_mode & 0o200 == 0)  # read-only like the rest of the package
        entry = next(item for item in self.manifest(request_id, "reviewer")["files"] if item["purpose"] == "diff")
        self.assertEqual(entry["path"], "candidate.diff")
        self.assertEqual(entry["sha256"], hashlib.sha256((package / "candidate.diff").read_bytes()).hexdigest())
        self.assertTrue(self.check(request_id)["ok"])
        self.assertIn("candidate.diff", self.assignment(request_id, 1, "reviewer").read_text(encoding="utf-8"))

    def test_the_diff_says_so_when_a_file_is_the_same_as_main_and_when_it_is_binary(self) -> None:
        request_id = self.staged_request()
        self.run_cli("dispatch", "--request", request_id, "--role", "builder")
        self.output(request_id, 1, "builder", "bdtt_repo/src/a.sql", "select 1;\n")
        path = self.rd(request_id) / "builder" / "outputs" / "attempt-001" / "bdtt_repo" / "src" / "blob.bin"
        path.write_bytes(bytes(range(256)))
        self.submit(request_id, "builder", "passed", "--output", "bdtt_repo/src/a.sql", "--output", "bdtt_repo/src/blob.bin")
        self.fill_assignment(request_id, 1, "reviewer")
        self.dispatch(request_id, "reviewer")
        diff = (self.package(request_id, "reviewer") / "candidate.diff").read_text(encoding="utf-8")
        self.assertIn("（和 main 上的版本一样，没有改动）", diff)
        self.assertIn("（二进制文件，不显示内容）", diff)

    def test_a_request_without_targets_gets_no_base_folder(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        request_id = self.new_request("plain")
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.reviewer_round(request_id, 1)
        self.assertFalse((self.package(request_id, "reviewer") / "base").exists())


class OutputTests(TargetCase):
    def ready(self) -> str:
        request_id = self.target_request(branch="feature/add_column")
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.run_cli("dispatch", "--request", request_id, "--role", "builder", "--from-target", "bdtt_repo/src/a.sql")
        return request_id

    def test_outputs_start_with_a_repository_name(self) -> None:
        request_id = self.ready()
        self.output(request_id, 1, "builder", "bdtt_repo/src/a.sql", "select 1, 2;\n")
        self.output(request_id, 1, "builder", "src/a.sql", "x\n")
        self.assertIn("第一段要是仓库名", self.submit(request_id, "builder", "passed", "--output", "src/a.sql", ok=False)["stderr"])
        self.run_cli("handoff", "submit", "--request", request_id, "--role", "builder", "--status", "passed", "--summary", "done", "--output", "bdtt_repo/src/a.sql")
        self.assertEqual(json.loads((self.rd(request_id) / "handoffs" / "builder" / "attempt-001" / "handoff.json").read_text(encoding="utf-8"))["outputs"], ["bdtt_repo/src/a.sql"])

    def test_an_unknown_repository_and_a_bare_repository_name_are_refused(self) -> None:
        request_id = self.ready()
        self.output(request_id, 1, "builder", "other_repo/a.sql", "x\n")
        stderr = self.submit(request_id, "builder", "passed", "--output", "other_repo/a.sql", ok=False)["stderr"]
        self.assertIn("已知的仓库：b9td_repo、bdtt_repo", stderr)

    def test_a_refused_path_is_refused_early(self) -> None:
        request_id = self.ready()
        self.output(request_id, 1, "builder", "bdtt_repo/.git/config", "x\n")
        stderr = self.submit(request_id, "builder", "passed", "--output", "bdtt_repo/.git/config", ok=False)["stderr"]
        self.assertIn("不能回写的路径", stderr)
        self.assertIn(".git/**", stderr)

    def test_a_refused_path_added_in_the_override_is_refused_too(self) -> None:
        self.override({"repos_root": str(self.repos), "refused_paths+": ["docs/**"]})
        request_id = self.ready()
        self.output(request_id, 1, "builder", "bdtt_repo/docs/x.md", "x\n")
        self.assertIn("docs/**", self.submit(request_id, "builder", "passed", "--output", "bdtt_repo/docs/x.md", ok=False)["stderr"])

    def test_evidence_may_be_anywhere_under_outputs(self) -> None:
        request_id = self.ready()
        self.output(request_id, 1, "builder", "bdtt_repo/src/a.sql", "x\n")
        self.output(request_id, 1, "builder", "evidence/test.log", "ok\n")
        self.submit(request_id, "builder", "passed", "--output", "bdtt_repo/src/a.sql", "--evidence", "evidence/test.log")

    def test_the_reviewer_gets_the_result_under_its_repository_name(self) -> None:
        request_id = self.ready()
        self.output(request_id, 1, "builder", "bdtt_repo/src/a.sql", "select 1, 2;\n")
        self.submit(request_id, "builder", "passed", "--output", "bdtt_repo/src/a.sql")
        self.fill_assignment(request_id, 1, "reviewer")
        self.dispatch(request_id, "reviewer")
        candidate = self.rd(request_id) / "handoffs" / "orchestrator" / "attempt-001" / "to-reviewer" / "candidate" / "bdtt_repo" / "src" / "a.sql"
        self.assertEqual(candidate.read_text(encoding="utf-8"), "select 1, 2;\n")
        self.assertTrue(self.check(request_id)["ok"])

    def test_a_request_without_targets_keeps_its_old_output_paths(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        request_id = self.new_request("plain")
        self.attempt(request_id)
        self.builder_round(request_id, 1)  # src/slug.py


class PromoteGuardTests(TargetCase):
    def test_promote_never_writes_into_the_harness_repository_for_a_request_with_targets(self) -> None:
        request_id = self.target_request(branch="feature/x")
        self.attempt(request_id)
        self.builder_round_for_target(request_id)
        self.promote_for_real(request_id)
        self.assertFalse((self.root / "bdtt_repo").exists())  # the result went to the target repository, not here
        self.assertTrue((self.bdtt / "src" / "a.sql").read_text(encoding="utf-8").startswith("select 1, 2;"))

    def test_the_request_cannot_be_ended_as_accepted_before_the_result_is_promoted(self) -> None:
        request_id = self.target_request(branch="feature/x")
        self.attempt(request_id)
        self.builder_round_for_target(request_id)
        message = self.refused("request", "set-status", "--request", request_id, "--status", "accepted")
        self.assertIn("request wait", message)
        self.assertIn("promote --dry-run", message)
        self.assertEqual(self.request(request_id)["status"], "open")
        self.run_cli("request", "set-status", "--request", request_id, "--status", "hitl", "--reason", "等用户")

    def builder_round_for_target(self, request_id: str) -> None:
        self.fill_assignment(request_id, 1, "builder")
        self.run_cli("dispatch", "--request", request_id, "--role", "builder", "--from-target", "bdtt_repo/src/a.sql")
        self.output(request_id, 1, "builder", "bdtt_repo/src/a.sql", "select 1, 2;\n")
        self.submit(request_id, "builder", "passed", "--output", "bdtt_repo/src/a.sql")
        self.reviewer_round(request_id, 1)


class TextTests(TargetCase):
    def test_the_assignment_names_the_repositories_only_for_a_request_with_targets(self) -> None:
        request_id = self.target_request()
        self.attempt(request_id)
        text = self.assignment(request_id, 1, "builder").read_text(encoding="utf-8")
        self.assertIn("成果路径的第一段也是仓库名", text)
        self.assertIn("`inputs/<仓库名>/<路径>`", text)
        self.assertIn("b9td_repo、bdtt_repo", text)
        self.run_cli("request", "set-status", "--request", request_id, "--status", "abandoned", "--reason", "x")
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        plain = self.new_request("plain")
        self.attempt(plain)
        self.assertNotIn("仓库名", self.assignment(plain, 1, "builder").read_text(encoding="utf-8"))

    def test_the_reviewer_assignment_points_at_candidate_and_base(self) -> None:
        request_id = self.target_request()
        self.attempt(request_id)
        text = self.assignment(request_id, 1, "reviewer").read_text(encoding="utf-8")
        self.assertIn("`candidate.diff`", text)
        self.assertIn("`candidate/<仓库名>/<路径>`", text)
        self.assertIn("`base/<仓库名>/<路径>`", text)

    def test_the_builder_is_told_the_repository_names_at_start(self) -> None:
        self.assertIn("第一段是仓库名（a、b）", handler.start_text("r1", "builder", 1, "a、b"))
        self.assertNotIn("仓库名", handler.start_text("r1", "builder", 1))
        request_id = self.target_request()
        self.assertEqual(handler.target_repo_names(self.root, request_id), "b9td_repo、bdtt_repo")
        self.assertEqual(handler.target_repo_names(self.root, "no-such-request"), "")

    def test_the_report_names_task_branch_and_repositories(self) -> None:
        request_id = self.target_request(branch="feature/add_column")
        self.add(request_id, "bdtt_repo/src/a.sql")
        report = self.run_cli("report", "--request", request_id)
        text = (self.root / report["report"]).read_text(encoding="utf-8")
        self.assertIn(f"任务目录：{TASK}", text)
        self.assertIn("分支：feature/add_column", text)
        self.assertIn(f"目标仓库：bdtt_repo，main 在 {self.main_commit(self.bdtt)[:12]}", text)


class CheckTests(TargetCase):
    def edit(self, request_id: str, **changes: Any) -> None:
        path = self.rd(request_id) / "request.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(changes)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_a_clean_request_with_targets_passes(self) -> None:
        request_id = self.target_request(branch="feature/x")
        self.add(request_id, "bdtt_repo/src/a.sql")
        self.assertTrue(self.check(request_id)["ok"])

    def test_a_bad_branch_and_a_missing_task_are_reported(self) -> None:
        request_id = self.target_request()
        self.edit(request_id, branch="feature/a-b", task=".workspace/current_tasks/gone")
        text = "\n".join(self.check(request_id)["problems"])
        self.assertIn("分支名 `feature/a-b` 不合法", text)
        self.assertIn("任务目录", text)

    def test_a_repository_that_is_no_longer_configured_is_reported(self) -> None:
        request_id = self.target_request()
        self.add(request_id, "bdtt_repo/src/a.sql")
        (self.repos / "bdtt_repo").rename(self.repos / "bdtt_repo_moved")
        self.assertIn("请求用过仓库 bdtt_repo", "\n".join(self.check(request_id)["problems"]))


class SchemaTests(unittest.TestCase):
    def test_the_new_fields_are_in_the_contracts(self) -> None:
        root = Path(__file__).resolve().parents[2] / ".harness" / "contracts"
        request = json.loads((root / "request.schema.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "manifest.schema.json").read_text(encoding="utf-8"))
        for key in ("task", "branch", "target_mode", "targets", "target_files"):
            self.assertIn(key, request["properties"])
        for key in ("repo", "blob", "base_commit"):
            self.assertIn(key, manifest["properties"]["files"]["items"]["properties"])
        self.assertTrue(targets.valid_branch("feature/ok_1"))


if __name__ == "__main__":
    unittest.main()
