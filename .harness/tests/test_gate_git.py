"""Gate and `.git` (B10-A4, M4-10): an agent never writes a `.git` folder or a path a target repository refuses.

The target repositories are real `git init` repositories in a temporary folder.
"""

from __future__ import annotations

import json
import unittest
from typing import Optional

from support import HarnessTestCase, pre_tool

from core import repo_paths
from core.state import update_state
from test_targets import GIT, make_repo


class FolderNameTests(unittest.TestCase):
    def test_every_spelling_of_a_git_folder_is_found(self) -> None:
        for path in (
            "/r/.git/config", "/r/.git", "/r/.GIT/HEAD", "C:/r/.git/hooks/pre-commit", "C:\\r\\.git\\config",
            "/r/.git./config", "/r/.git/../.git/x", "/r/GIT~1/config", "/r/.git::$INDEX_ALLOCATION/config", "/r/.git /config",
        ):
            with self.subTest(path):
                self.assertTrue(repo_paths.has_git_folder(path))

    def test_similar_names_are_not(self) -> None:
        for path in ("/r/.gitignore", "/r/.github/workflows/a.yml", "/r/.gitattributes", "/r/x.git/y", "/r/git/y", "/r/.gitmodules"):
            with self.subTest(path):
                self.assertFalse(repo_paths.has_git_folder(path))


@unittest.skipUnless(GIT, "git is not installed")
class GateGitTests(HarnessTestCase):
    session = "gate-git"

    def setUp(self) -> None:
        super().setUp()
        self.base = str(self.root.resolve())
        self.repos = self.root.resolve() / "source" / "repos"
        make_repo(self.repos / "bdtt_repo", {"src/a.sql": "select 1;\n", ".github/workflows/ci.yml": "x\n"})
        make_repo(self.repos / "b9td_repo", {"a.sql": "select 9;\n"})
        self.override({"repos_root": str(self.repos)})

    def override(self, data: dict) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text(json.dumps(data), encoding="utf-8")

    def pre(self, tool: str, tool_input: dict, cwd: Optional[str] = None) -> dict:
        data = pre_tool(self.session, tool, tool_input)
        data["cwd"] = cwd or self.base
        return self.hook(data)

    def decision(self, output: dict) -> str:
        return output.get("hookSpecificOutput", {}).get("permissionDecision", "")

    def reason(self, output: dict) -> str:
        return output["hookSpecificOutput"]["permissionDecisionReason"]

    def edit(self, path: str, cwd: Optional[str] = None) -> dict:
        return self.pre("create_file", {"filePath": path, "content": "x"}, cwd)

    def term(self, command: str, cwd: Optional[str] = None) -> dict:
        return self.pre("run_in_terminal", {"command": command, "explanation": "t", "isBackground": False}, cwd)

    def enter_l3(self) -> None:
        def mutate(state: dict) -> None:
            state["active_request"] = "20261002-1200-demo-ab12"

        update_state(self.root, "vscode", self.session, mutate)

    # --- edit tools -----------------------------------------------------------------------------

    def test_an_edit_tool_cannot_write_in_a_target_git_folder(self) -> None:
        for path in (
            f"{self.repos}/bdtt_repo/.git/config", f"{self.repos}/bdtt_repo/.git/hooks/pre-commit", f"{self.repos}/b9td_repo/.git/HEAD",
            f"{self.repos}/bdtt_repo/.GIT/config", f"{self.repos}/bdtt_repo/.git./config", f"{self.repos}/bdtt_repo/GIT~1/config",
            f"{self.repos}/bdtt_repo/.git::$INDEX_ALLOCATION/config", f"{self.repos}/bdtt_repo/src/../.git/config",
        ):
            with self.subTest(path):
                output = self.edit(path)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn(".git", self.reason(output))

    def test_a_relative_path_is_read_against_the_cwd(self) -> None:
        self.assertEqual(self.decision(self.edit(".git/config", cwd=f"{self.repos}/bdtt_repo")), "deny")
        self.assertEqual(self.decision(self.edit("hooks/pre-commit", cwd=f"{self.repos}/bdtt_repo/.git")), "deny")

    def test_every_level_is_covered(self) -> None:
        self.assertEqual(self.decision(self.edit(f"{self.repos}/bdtt_repo/.git/config")), "deny")
        self.enter_l3()
        output = self.edit(f"{self.repos}/bdtt_repo/.git/config")
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("`.git` 文件夹", self.reason(output))  # the specific reason, not the generic L3 one

    def test_the_floor_needs_no_target_configuration(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").unlink()
        self.assertEqual(self.decision(self.edit("/somewhere/else/.git/config")), "deny")
        self.assertEqual(self.decision(self.edit(f"{self.base}/.git/config")), "deny")

    def test_a_broken_target_policy_does_not_open_the_floor_or_break_the_gate(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual(self.decision(self.edit(f"{self.repos}/bdtt_repo/.git/config")), "deny")
        self.assertEqual(self.edit(f"{self.repos}/bdtt_repo/src/a.sql"), {})

    def test_the_working_tree_of_a_target_repository_is_written_by_promote_only(self) -> None:
        """M7-4: no Level edits a file of a target repository directly. The reason names the way that works."""
        for path in (
            f"{self.repos}/bdtt_repo/src/a.sql", f"{self.repos}/bdtt_repo/.gitignore", f"{self.repos}/bdtt_repo/.github/workflows/ci.yml",
            f"{self.repos}/bdtt_repo/.gitattributes", f"{self.repos}/bdtt_repo/x.git/y", f"{self.repos}/BDTT_REPO/new/file.sql",
        ):
            with self.subTest(path):
                output = self.edit(path)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn("只能由 promote 写", self.reason(output))
        self.assertIn("task fetch", self.reason(self.edit(f"{self.repos}/bdtt_repo/src/a.sql")))
        self.assertEqual(self.pre("read_file", {"filePath": f"{self.repos}/bdtt_repo/src/a.sql"}), {})  # reading stays free
        self.assertEqual(self.edit(f"{self.repos}/not_a_repo.txt"), {})  # beside the repositories, not in one
        self.enter_l3()
        self.assertIn("请求目录", self.reason(self.edit(f"{self.repos}/bdtt_repo/src/a.sql")))

    def test_terminal_writes_into_a_target_working_tree_are_denied(self) -> None:
        repo = f"{self.repos}/bdtt_repo"
        for command in (
            f"echo x > {repo}/.gitignore", f"cp a {repo}/.github/x.yml", f"rm {repo}/src/a.sql.bak", f"sed -i '' 's/1/2/' {repo}/src/a.sql",
            f"mv {repo}/src/a.sql {repo}/src/b.sql", f"mkdir -p {repo}/new", f"printf x | tee {repo}/src/a.sql",
            f"python3 -c \"open('{repo}/src/a.sql','w').write('x')\"",
        ):
            with self.subTest(command):
                output = self.term(command)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn("只能由 promote 写", self.reason(output))

    def test_reads_of_a_git_folder_are_not_blocked(self) -> None:
        self.assertEqual(self.pre("read_file", {"filePath": f"{self.repos}/bdtt_repo/.git/config"}), {})

    # --- refused_paths --------------------------------------------------------------------------

    def test_refused_paths_of_a_repository_are_denied_for_an_edit_tool(self) -> None:
        self.override({"repos_root": str(self.repos), "repos": {"bdtt_repo": {"refused_paths": [".git/**", ".github/workflows/**", "*.pem"]}}})
        output = self.edit(f"{self.repos}/bdtt_repo/.github/workflows/ci.yml")
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("bdtt_repo/.github/workflows/ci.yml", self.reason(output))
        self.assertIn("refused_paths", self.reason(output))
        self.assertEqual(self.decision(self.edit(f"{self.repos}/bdtt_repo/key.pem")), "deny")
        self.assertEqual(self.decision(self.edit(f"{self.repos}/BDTT_REPO/.GITHUB/Workflows/ci.yml")), "deny")
        # another repository keeps its own list: there the path is refused as any other file of a working tree
        self.assertNotIn("refused_paths", self.reason(self.edit(f"{self.repos}/b9td_repo/.github/workflows/ci.yml")))

    def test_a_root_wide_refused_path_applies_to_every_repository(self) -> None:
        self.override({"repos_root": str(self.repos), "refused_paths": [".git/**", "secrets/**"]})
        for name in ("bdtt_repo", "b9td_repo"):
            self.assertEqual(self.decision(self.edit(f"{self.repos}/{name}/secrets/a.txt")), "deny", name)

    # --- terminal -------------------------------------------------------------------------------

    def test_terminal_writes_into_a_git_folder_are_denied(self) -> None:
        repo = f"{self.repos}/bdtt_repo"
        for command in (
            f"rm -rf {repo}/.git", f"rm {repo}/.git/index.lock", f"echo x > {repo}/.git/config", f"echo x >> .git/hooks/pre-commit",
            f"cp /tmp/hook {repo}/.git/hooks/pre-commit", f"mv {repo}/.git /tmp/g", f"sed -i 's/a/b/' {repo}/.git/config",
            f"printf x | tee {repo}/.git/HEAD", f"chmod +x {repo}/.git/hooks/pre-commit", f"touch .git/x", "rm -rf .GIT",
            f"cd {repo} && rm -rf .git", "Remove-Item -Recurse C:\\r\\.git", f"python3 -c \"open('{repo}/.git/config','w').write('x')\"",
            f"rm {repo}/.git./config", f"rm -rf {repo}/GIT~1",
        ):
            with self.subTest(command):
                output = self.term(command)
                self.assertEqual(self.decision(output), "deny")
                self.assertIn(".git", self.reason(output))

    def test_terminal_reads_and_normal_git_commands_are_not_this_rules_business(self) -> None:
        repo = f"{self.repos}/bdtt_repo"
        for command in (
            f"cat {repo}/.git/config", f"ls {repo}/.git", f"git -C {repo} status", f"git -C {repo} log --oneline", f"git -C {repo} diff",
            f"cp {repo}/.git/config /tmp/c", f"cp {repo}/src/a.sql /tmp/a.sql", f"cat {repo}/src/a.sql", f"grep -rn select {repo}/src",
            f"rg 'rm -rf .git' {repo}/src", "git status", f"git -C {repo} show main:src/a.sql",
        ):
            with self.subTest(command):
                self.assertNotEqual(self.decision(self.term(command)), "deny")

    def test_terminal_writes_to_a_refused_path_are_denied(self) -> None:
        self.override({"repos_root": str(self.repos), "repos": {"bdtt_repo": {"refused_paths": [".git/**", ".github/workflows/**"]}}})
        repo = f"{self.repos}/bdtt_repo"
        self.assertEqual(self.decision(self.term(f"echo x > {repo}/.github/workflows/ci.yml")), "deny")
        self.assertEqual(self.decision(self.term(f"rm {repo}/.github/workflows/ci.yml")), "deny")
        self.assertIn("不许写的路径", self.reason(self.term(f"echo x > {repo}/.github/workflows/ci.yml")))
        self.assertNotEqual(self.decision(self.term(f"cat {repo}/.github/workflows/ci.yml")), "deny")

    def test_windows_spelling_of_a_target_path_in_a_command(self) -> None:
        self.assertEqual(self.decision(self.term("del C:\\repos\\bdtt_repo\\.git\\index")), "deny")
        self.assertEqual(self.decision(self.term("echo x > C:\\repos\\bdtt_repo\\.GIT\\config")), "deny")


if __name__ == "__main__":
    unittest.main()
