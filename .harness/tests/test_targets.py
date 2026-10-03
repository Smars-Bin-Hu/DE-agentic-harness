"""Target repositories (B10-A1, M4-10): target.json, finding repositories, reading them with git, `target list|show`, doctor.

The repositories are real git repositories made with `git init` in a temporary folder. Without git, these tests are skipped.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional

import support  # noqa: F401  (puts the engine on sys.path)
from core import targets
from support import REPO, HarnessTestCase

GIT = shutil.which("git")
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def run_git(path: Path, *arguments: str) -> str:
    done = subprocess.run(["git", "-C", str(path), *arguments], capture_output=True, text=True, env={**os.environ, **IDENTITY}, check=True)
    return done.stdout.strip()


def make_repo(path: Path, files: Optional[Dict[str, str]] = None, branch: str = "main") -> Path:
    """A git repository with one commit on `branch`."""
    path.mkdir(parents=True)
    run_git(path, "init", "-q")
    run_git(path, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    for name, body in (files or {"README.md": "x\n"}).items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    run_git(path, "add", "-A")
    run_git(path, "commit", "-q", "-m", "first")
    return path


class PolicyTests(unittest.TestCase):
    def policy(self) -> dict:
        return json.loads((REPO / ".harness" / "policies" / "target.json").read_text(encoding="utf-8"))

    def test_the_shipped_policy_is_valid_and_has_no_repository(self) -> None:
        policy = self.policy()
        targets.validate_policy(policy)
        self.assertEqual(policy["repos_root"], "")
        self.assertEqual(policy["repos"], {})
        self.assertEqual(policy["base_ref"], "main")
        self.assertIn(".git/**", policy["refused_paths"])

    def test_wrong_shapes_are_refused(self) -> None:
        for change in (
            lambda p: p.update(repos_root=3),
            lambda p: p.update(base_ref=""),
            lambda p: p.update(refused_paths="x"),
            lambda p: p["repos"].update(a="x"),
            lambda p: p["repos"].update(a={"unknown": 1}),
            lambda p: p["repos"].update({"bad/name": {"path": "x"}}),
            lambda p: p["repos"].update({"..": {"path": "x"}}),
            lambda p: p.update(git_timeout_seconds=0),
        ):
            policy = self.policy()
            change(policy)
            with self.subTest(policy):
                with self.assertRaises(ValueError):
                    targets.validate_policy(policy)


@unittest.skipUnless(GIT, "git is not installed")
class LoadTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repos = self.root / "source" / "repos"
        make_repo(self.repos / "bdtt_repo")
        make_repo(self.repos / "b9td_repo")
        (self.repos / "not_a_repo").mkdir()
        (self.repos / "notes.txt").write_text("x", encoding="utf-8")

    def override(self, data: dict) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps(data), encoding="utf-8")

    def test_nothing_configured_means_not_configured(self) -> None:
        found = targets.load(self.root)
        self.assertFalse(found.configured)
        self.assertEqual(found.repos, {})

    def test_every_git_folder_under_repos_root_is_a_repository_named_after_the_folder(self) -> None:
        self.override({"repos_root": str(self.repos)})
        found = targets.load(self.root)
        self.assertTrue(found.configured)
        self.assertEqual(found.names(), ["b9td_repo", "bdtt_repo"])
        self.assertEqual(found.get("bdtt_repo").path, self.repos / "bdtt_repo")
        self.assertEqual(found.get("bdtt_repo").base_ref, "main")
        self.assertEqual(found.problems, [])

    def test_a_repository_elsewhere_is_added_by_name(self) -> None:
        other = make_repo(self.root / "elsewhere" / "extra")
        self.override({"repos_root": str(self.repos), "repos": {"extra_repo": {"path": str(other)}}})
        self.assertEqual(targets.load(self.root).names(), ["b9td_repo", "bdtt_repo", "extra_repo"])

    def test_settings_for_a_found_repository_change_only_that_one(self) -> None:
        self.override({"repos_root": str(self.repos), "repos": {"bdtt_repo": {"base_ref": "develop", "refused_paths": ["docs/**"]}}})
        found = targets.load(self.root)
        self.assertEqual(found.get("bdtt_repo").base_ref, "develop")
        self.assertEqual(found.get("bdtt_repo").refused_paths, ["docs/**"])
        self.assertEqual(found.get("b9td_repo").base_ref, "main")
        self.assertEqual(found.get("b9td_repo").refused_paths, [".git/**"])

    def test_refused_paths_can_be_appended_for_every_repository(self) -> None:
        self.override({"repos_root": str(self.repos), "refused_paths+": [".github/workflows/**"]})
        self.assertEqual(targets.load(self.root).get("bdtt_repo").refused_paths, [".git/**", ".github/workflows/**"])

    def test_problems_are_listed_not_raised(self) -> None:
        self.override({
            "repos_root": str(self.root / "missing"),
            "repos": {"ghost": {"base_ref": "x"}, "broken": {"path": str(self.repos / "not_a_repo")}},
        })
        found = targets.load(self.root)
        self.assertEqual(found.repos, {})
        text = "\n".join(found.problems)
        self.assertIn("repos_root 不存在", text)
        self.assertIn("ghost", text)
        self.assertIn("broken", text)

    def test_an_unknown_name_names_the_known_ones(self) -> None:
        self.override({"repos_root": str(self.repos)})
        with self.assertRaises(targets.TargetError) as caught:
            targets.load(self.root).get("nope")
        self.assertIn("b9td_repo", str(caught.exception))
        self.assertIn("bdtt_repo", str(caught.exception))

    def test_a_home_folder_and_an_environment_variable_in_the_path_are_expanded(self) -> None:
        self.override({"repos_root": "%HARNESS_TEST_REPOS%" if os.name == "nt" else "$HARNESS_TEST_REPOS"})
        os.environ["HARNESS_TEST_REPOS"] = str(self.repos)
        self.addCleanup(os.environ.pop, "HARNESS_TEST_REPOS", None)
        self.assertEqual(targets.load(self.root).names(), ["b9td_repo", "bdtt_repo"])


@unittest.skipUnless(GIT, "git is not installed")
class ReadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.path = make_repo(Path(self._temporary.name) / "my repo", {"a.txt": "a\n", "dir/b.txt": "b\n"})
        self.repo = targets.Repo("my_repo", self.path, "main")

    def test_the_base_commit_and_date(self) -> None:
        commit = targets.ref_commit(self.repo)
        self.assertEqual(commit, run_git(self.path, "rev-parse", "main"))
        self.assertRegex(targets.commit_date(self.repo, commit), r"^\d{4}-\d\d-\d\dT")

    def test_a_missing_branch_is_an_empty_commit(self) -> None:
        self.assertEqual(targets.ref_commit(targets.Repo("r", self.path, "nope")), "")

    def test_the_branch_in_use_and_a_detached_head(self) -> None:
        run_git(self.path, "switch", "-q", "-c", "other")
        self.assertEqual(targets.current_branch(self.repo), "other")
        run_git(self.path, "switch", "-q", "--detach", "main")
        self.assertEqual(targets.current_branch(self.repo), "(detached)")

    def test_clean_modified_and_untracked(self) -> None:
        self.assertEqual(targets.dirty_paths(self.repo), [])
        (self.path / "a.txt").write_text("changed\n", encoding="utf-8")
        (self.path / "dir" / "new.txt").write_text("n\n", encoding="utf-8")
        self.assertEqual(sorted(targets.dirty_paths(self.repo)), ["a.txt", "dir/new.txt"])

    def test_a_path_with_a_space_and_non_ascii_name_is_read(self) -> None:
        (self.path / "报表 1.sql").write_text("select 1\n", encoding="utf-8")
        self.assertEqual(targets.dirty_paths(self.repo), ["报表 1.sql"])

    def test_a_git_failure_says_which_repository(self) -> None:
        with self.assertRaises(targets.TargetError) as caught:
            targets.git(self.repo, "no-such-command")
        self.assertIn("my_repo", str(caught.exception))

    def test_a_missing_git_is_said_plainly(self) -> None:
        saved = os.environ["PATH"]
        os.environ["PATH"] = ""
        try:
            with self.assertRaises(targets.TargetError) as caught:
                targets.git(self.repo, "status")
        finally:
            os.environ["PATH"] = saved
        self.assertIn("找不到 git", str(caught.exception))


class LocationTests(unittest.TestCase):
    def test_a_long_windows_path_is_a_warning(self) -> None:
        long_path = "C:\\" + "a" * 100
        self.assertTrue(targets.location_warnings(long_path, windows=True))
        self.assertEqual(targets.location_warnings(long_path, windows=False), [])
        self.assertEqual(targets.location_warnings("C:\\dev\\harness", windows=True), [])

    def test_onedrive_is_a_warning_on_any_system(self) -> None:
        self.assertTrue(targets.location_warnings("/Users/x/OneDrive - Company/harness", windows=False))


@unittest.skipUnless(GIT, "git is not installed")
class CommandTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repos = self.root / "source" / "repos"
        make_repo(self.repos / "bdtt_repo", {"a.sql": "select 1\n"})
        make_repo(self.repos / "b9td_repo")
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps({"repos_root": str(self.repos)}), encoding="utf-8")

    def test_target_list(self) -> None:
        result = self.cli_json("target", "list")
        self.assertTrue(result["configured"])
        self.assertEqual([item["name"] for item in result["repos"]], ["b9td_repo", "bdtt_repo"])
        item = result["repos"][1]
        self.assertEqual(item["path"], str(self.repos / "bdtt_repo"))
        self.assertEqual(item["base_commit"], run_git(self.repos / "bdtt_repo", "rev-parse", "main")[:12])
        self.assertTrue(item["clean"])
        self.assertEqual(item["current_branch"], "main")
        self.assertEqual(result["problems"], [])

    def test_target_list_says_when_nothing_is_configured(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        result = self.cli_json("target", "list")
        self.assertEqual((result["configured"], result["repos"]), (False, []))

    def test_target_show_one_and_an_unknown_one(self) -> None:
        self.assertEqual(self.cli_json("target", "show", "--repo", "bdtt_repo")["name"], "bdtt_repo")
        done = self.cli("target", "show", "--repo", "nope")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("bdtt_repo", done.stderr)

    def test_dirty_shows_in_the_list(self) -> None:
        (self.repos / "bdtt_repo" / "a.sql").write_text("select 2\n", encoding="utf-8")
        item = self.cli_json("target", "list")["repos"][1]
        self.assertFalse(item["clean"])
        self.assertEqual(item["uncommitted_files"], 1)


@unittest.skipUnless(GIT, "git is not installed")
class DoctorTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        for name in (".github", ".harness"):
            shutil.copytree(REPO / name, self.root / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "runtime", "*.pyc", "*.override.json"))
        (self.root / ".workspace").mkdir(exist_ok=True)
        shutil.copy(REPO / ".workspace" / "README.md", self.root / ".workspace" / "README.md")
        self.repos = self.root / "source" / "repos"
        make_repo(self.repos / "bdtt_repo")

    def override(self, data: dict) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps(data), encoding="utf-8")

    def doctor(self) -> subprocess.CompletedProcess:
        return self.cli("doctor")

    def test_nothing_configured_is_fine(self) -> None:
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("没有配置目标仓库", result.stdout)

    def test_repositories_are_listed_with_their_state(self) -> None:
        self.override({"repos_root": str(self.repos)})
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("目标仓库 bdtt_repo：main 在", result.stdout)
        self.assertIn("工作区干净", result.stdout)

    def test_uncommitted_files_are_said_but_are_not_an_error(self) -> None:
        self.override({"repos_root": str(self.repos)})
        (self.repos / "bdtt_repo" / "x.txt").write_text("x", encoding="utf-8")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 个未提交的文件", result.stdout)

    def test_a_missing_repos_root_is_an_error(self) -> None:
        self.override({"repos_root": str(self.root / "missing")})
        result = self.doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("repos_root 不存在", result.stdout)

    def test_a_missing_base_branch_is_an_error(self) -> None:
        self.override({"repos_root": str(self.repos), "base_ref": "develop"})
        result = self.doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("本地没有分支 `develop`", result.stdout)

    def test_an_empty_repos_root_is_a_warning(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        self.override({"repos_root": str(empty)})
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("下没有 git 仓库", result.stdout)

    def test_a_broken_policy_is_an_error(self) -> None:
        self.override({"repos_root": 3})
        self.assertEqual(self.doctor().returncode, 1)


if __name__ == "__main__":
    unittest.main()
