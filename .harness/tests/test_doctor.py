"""cli.py doctor, and repository layout rules that doctor does not cover."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import CLI, ENGINE, REPO


def copy_repo(destination: Path) -> None:
    """The parts of the repository that doctor looks at."""
    ignore = shutil.ignore_patterns("__pycache__", "runtime", "*.pyc", "*.override.json")
    shutil.copytree(REPO / ".github", destination / ".github", ignore=ignore)
    shutil.copytree(REPO / ".harness", destination / ".harness", ignore=ignore)
    (destination / ".workspace").mkdir()
    shutil.copy(REPO / ".workspace" / "README.md", destination / ".workspace" / "README.md")  # a module lists it


# The release data the banner prints: read it, so a version bump does not break the tests.
REGISTRY = json.loads((REPO / ".harness" / "registry.json").read_text(encoding="utf-8"))
VERSION = REGISTRY["version"]

# The Level entry skills are an exception to the prefix rule (skills.instructions.md).
LEVEL_ENTRY_SKILLS = ("l1", "l2", "l3")

class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        copy_repo(self.root)

    def env(self, **extra: str) -> dict:
        """The environment of a machine that is set up: the launcher of this copy is in PATH."""
        path = str(self.root / ".harness" / "bin") + os.pathsep + os.environ.get("PATH", "")
        return {**os.environ, "HARNESS_ROOT": str(self.root), "PATH": path, **extra}

    def doctor(self, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLI), "doctor"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=self.env(**extra),
            check=False,
        )

    def doctor_as(self, encoding: str) -> bytes:
        """doctor with stdout in `encoding`, as a Windows pipe has it. The bytes, not decoded."""
        return subprocess.run(
            [sys.executable, str(CLI), "doctor"],
            capture_output=True,
            env=self.env(PYTHONIOENCODING=encoding),
            check=False,
        ).stdout

    def test_it_says_how_chinese_is_printed_here(self) -> None:
        """ISSUE-20261005-03: on a pipe that cannot show Chinese the CLI prints \\uXXXX; doctor shows what UTF-8 would look like."""
        fine = self.doctor().stdout
        self.assertIn("输出编码：stdout=utf-8", fine)
        self.assertIn("output.encoding=auto", fine)
        self.assertIn("中文样例：成果已写入（这一行能读", fine)
        self.assertNotIn("UTF-8 样例", fine)
        narrow = self.doctor_as("cp1252")
        self.assertIn(b"[WARN]  \\u8f93\\u51fa\\u7f16\\u7801", narrow)  # 输出编码, escaped: what the company machine showed
        self.assertIn(b"stdout=cp1252", narrow)
        sample = [line for line in narrow.splitlines() if line.startswith(b"[INFO]")]
        self.assertEqual(len(sample), 1)
        self.assertIn("UTF-8 样例：中文样例：成果已写入", sample[0].decode("utf-8"))  # raw UTF-8 bytes, whatever the stream is
        self.assertIn("cli.override.json", sample[0].decode("utf-8"))
        self.assertTrue(narrow.rstrip().endswith(b'{"errors": 0}'))

    def test_the_switch_prints_utf8_whatever_the_terminal_says(self) -> None:
        (self.root / ".harness" / "policies" / "cli.override.json").write_text('{"output": {"encoding": "utf-8"}}', encoding="utf-8")
        text = self.doctor_as("cp1252").decode("utf-8")
        self.assertIn("输出编码：stdout=utf-8", text)
        self.assertIn("output.encoding=utf-8", text)
        self.assertNotIn("\\u", text)
        refused = subprocess.run(
            [sys.executable, str(CLI), "task", "status"], capture_output=True, check=False,
            env=self.env(PYTHONIOENCODING="cp1252"),
        )
        self.assertIn("没有进行中的任务", refused.stderr.decode("utf-8"))  # stderr follows the switch too

    def test_a_wrong_or_broken_output_setting_is_reported_and_printing_goes_on(self) -> None:
        override = self.root / ".harness" / "policies" / "cli.override.json"
        override.write_text('{"output": {"encoding": "gbk"}}', encoding="utf-8")
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("output.encoding 是 `gbk`", result.stdout)
        self.assertIn("output.encoding=auto", result.stdout)
        override.write_text("{not json", encoding="utf-8")
        result = self.doctor()
        self.assertIn("[ERROR]", result.stdout)
        self.assertEqual(self.version().stdout.strip(), f"harness {VERSION}")  # the CLI still prints

    def edit_json(self, relative: str, change) -> None:
        path = self.root / relative
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_a_clean_copy_passes(self) -> None:
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("[ERROR]", result.stdout)

    def version(self, *flags: str) -> subprocess.CompletedProcess:
        """`--version --short`: one line, for scripts. Pass `flags=("--version",)` for the banner."""
        return subprocess.run(
            [sys.executable, str(CLI), *(flags or ("--version", "--short"))],
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=self.env(),
            check=False,
        )

    def test_version_prints_the_registry_version(self) -> None:
        result = self.version()
        self.assertEqual((result.returncode, result.stdout.strip()), (0, f"harness {VERSION}"), result.stderr)

    def test_user_gives_the_name_from_the_override_and_else_from_git(self) -> None:
        """M9-2: the name an agent writes where a file needs an author."""
        def who() -> dict:
            done = subprocess.run([sys.executable, str(CLI), "user"], text=True, encoding="utf-8", capture_output=True, env=self.env(), check=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            return json.loads(done.stdout)

        self.assertIn(who()["source"], ("git", "none"))  # the copy is no git repository: whatever git says for this machine
        override = self.root / ".harness" / "policies" / "user.override.json"
        override.write_text('{"name": "  胡斌  "}', encoding="utf-8")
        self.assertEqual(who(), {"name": "胡斌", "source": "user.override.json"})
        self.assertIn("用户名字：胡斌（来自 user.override.json）", self.doctor().stdout)
        override.write_text('{"name": 7}', encoding="utf-8")
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("user.json 的 name 要是一段文字", result.stdout)

    def test_version_shows_the_banner_with_the_release_date_and_the_authors(self) -> None:
        """M9-1. ASCII only, so it shows on a terminal of any encoding."""
        result = self.version("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertTrue(lines[4].endswith(f"version {VERSION}"), lines)
        self.assertEqual(lines[6:], ["Copilot Agentic Harness", f"Released {REGISTRY['released']}", f"Copyright (c) {REGISTRY['released'][:4]} {REGISTRY['copyright']}", "Contributors: " + ", ".join(REGISTRY["contributors"])])
        self.assertTrue(result.stdout.isascii())
        self.assertEqual(self.version("--short", "--version").stdout.strip(), f"harness {VERSION}")  # the order does not matter
        self.edit_json(".harness/registry.json", lambda data: [data.pop(key) for key in ("released", "copyright", "contributors")])
        bare = self.version("--version").stdout.splitlines()
        self.assertEqual(bare[6:], ["Copilot Agentic Harness"])  # the three fields are optional
        self.edit_json(".harness/registry.json", lambda data: data.update(released="October 2026"))
        self.assertEqual(self.version("--version").returncode, 1)

    def test_version_follows_the_registry_and_the_registry_needs_it_in_the_x_y_z_form(self) -> None:
        self.edit_json(".harness/registry.json", lambda data: data.update(version="2.3.4"))
        self.assertEqual(self.version().stdout.strip(), "harness 2.3.4")
        self.edit_json(".harness/registry.json", lambda data: data.update(version="v2"))
        self.assertEqual(self.version().returncode, 1)
        self.assertNotEqual(self.doctor().returncode, 0)

    def test_a_broken_registry_does_not_break_the_other_commands(self) -> None:
        (self.root / ".harness" / "registry.json").write_text("{", encoding="utf-8")
        self.assertEqual(self.version().returncode, 1)
        result = self.doctor()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("registry.json", result.stdout)

    def test_the_real_repository_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CLI), "doctor"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            env={key: value for key, value in os.environ.items() if key != "HARNESS_ROOT"},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_deleted_registered_file_is_an_error(self) -> None:
        (self.root / ".harness" / "tests" / "test_task_level.py").unlink()
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("test_task_level.py", result.stdout)

    def test_a_deleted_registered_directory_is_an_error(self) -> None:
        shutil.rmtree(self.root / ".github" / "skills" / "harness-task-level")
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("harness-task-level", result.stdout)

    def test_a_deleted_engine_file_is_an_error(self) -> None:
        (self.root / ".harness" / "engine" / "adapters" / "copilot_cli.py").unlink()
        self.assertEqual(self.doctor().returncode, 1)

    def test_a_second_hook_config_is_an_error(self) -> None:
        shutil.copy(self.root / ".github" / "hooks" / "harness.json", self.root / ".github" / "hooks" / "extra.json")
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("只保留一份", result.stdout)

    def test_a_hook_command_that_does_not_call_hook_py_is_an_error(self) -> None:
        def change(data: dict) -> None:
            data["hooks"]["PreToolUse"][0]["command"] = "python3 something_else.py"

        self.edit_json(".github/hooks/harness.json", change)
        self.assertEqual(self.doctor().returncode, 1)

    def test_a_windows_command_is_checked_too(self) -> None:
        def change(data: dict) -> None:
            data["hooks"]["PreToolUse"][0]["windows"] = "python other.py"

        self.edit_json(".github/hooks/harness.json", change)
        self.assertEqual(self.doctor().returncode, 1)

    def test_every_hook_entry_needs_the_keys_of_both_engines(self) -> None:
        for key in ("command", "windows", "bash", "powershell"):
            with self.subTest(key):
                def change(data: dict, key: str = key) -> None:
                    del data["hooks"]["PreToolUse"][0][key]

                self.edit_json(".github/hooks/harness.json", change)
                result = self.doctor()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"缺少 `{key}`", result.stdout)
                shutil.copy(REPO / ".github" / "hooks" / "harness.json", self.root / ".github" / "hooks" / "harness.json")

    def test_a_windows_key_that_uses_python3_is_an_error(self) -> None:
        for key in ("windows", "powershell"):
            with self.subTest(key):
                def change(data: dict, key: str = key) -> None:
                    data["hooks"]["Stop"][0][key] = "python3 .harness/engine/hook.py"

                self.edit_json(".github/hooks/harness.json", change)
                result = self.doctor()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"`{key}` 应该用 `python`", result.stdout)
                shutil.copy(REPO / ".github" / "hooks" / "harness.json", self.root / ".github" / "hooks" / "harness.json")

    def test_a_missing_event_in_the_hook_config_is_an_error(self) -> None:
        def change(data: dict) -> None:
            del data["hooks"]["SubagentStop"]

        self.edit_json(".github/hooks/harness.json", change)
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("SubagentStop", result.stdout)

    def test_an_event_nobody_needs_is_only_a_warning(self) -> None:
        def change(data: dict) -> None:
            data["hooks"]["PreCompact"] = data["hooks"]["Stop"]

        self.edit_json(".github/hooks/harness.json", change)
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("[WARN]", result.stdout)

    def test_a_broken_policy_is_an_error(self) -> None:
        def change(data: dict) -> None:
            data["levels"]["1"]["budget_per_prompt"]["repository_searches"]["limit"] = "two"

        self.edit_json(".harness/policies/task-levels.json", change)
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("task-levels.json", result.stdout)

    def test_a_broken_override_is_caught_by_the_same_check(self) -> None:
        (self.root / ".harness" / "policies" / "task-levels.override.json").write_text(
            json.dumps({"levels": {"2": {"subagents": {"allowed": "yes"}}}}), encoding="utf-8"
        )
        self.assertEqual(self.doctor().returncode, 1)

    # --- interpreter and cross-platform text -----------------------------------------------------

    def test_a_missing_interpreter_is_a_warning(self) -> None:
        result = self.doctor(PATH=str(self.root / ".harness" / "bin"))  # the launcher is there, python is not
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PATH 里找不到 `python", result.stdout)

    def test_the_short_command_must_be_in_path(self) -> None:
        """M9-5: every command an agent is given starts with `harness`."""
        fine = self.doctor()
        self.assertIn("[OK]    短命令 `harness` 在 PATH 里", fine.stdout)
        empty = self.root / "empty-path"
        empty.mkdir()
        missing = self.doctor(PATH=str(empty))
        self.assertEqual(missing.returncode, 1)
        self.assertIn("[ERROR] PATH 里找不到短命令 `harness`", missing.stdout)
        self.assertIn(str(self.root / ".harness" / "bin"), missing.stdout)  # the folder to add
        self.assertIn("harness-repo-initialize", missing.stdout)

    @unittest.skipIf(os.name == "nt", "a shell script as a stand-in launcher")
    def test_a_launcher_of_another_copy_is_a_warning(self) -> None:
        other = self.root / "other-bin"
        other.mkdir()
        (other / "harness").write_text("#!/bin/sh\n", encoding="utf-8")
        (other / "harness").chmod(0o755)
        result = self.doctor(PATH=str(other) + os.pathsep + os.environ.get("PATH", "").replace(str(Path.home() / "bin"), ""))
        self.assertIn("不是这个仓库的 `.harness/bin/`", result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout)

    @unittest.skipIf(os.name == "nt", "the shell launcher; harness.cmd follows the same steps")
    def test_a_copy_of_the_launcher_in_a_fixed_folder_works_and_doctor_accepts_it(self) -> None:
        """A fixed folder in PATH holds a copy of the launcher, so a new version never needs a PATH change."""
        fixed = self.root / "fixed-bin"
        fixed.mkdir()
        shutil.copy(self.root / ".harness" / "bin" / "harness", fixed / "harness")
        (fixed / "harness").chmod(0o755)
        outside_dir = tempfile.TemporaryDirectory()  # not under the repository copy, or the upward search would find it
        self.addCleanup(outside_dir.cleanup)
        outside = Path(outside_dir.name).resolve()

        def run(cwd: Path, **extra: str) -> "subprocess.CompletedProcess[str]":
            env = {key: value for key, value in os.environ.items() if key not in ("HARNESS_ROOT", "HARNESS_HOME")}
            return subprocess.run([str(fixed / "harness"), "--version", "--short"], cwd=cwd, capture_output=True, text=True, check=False, env={**env, **extra})

        inside = run(self.root / ".harness")  # inside a repository: that one is used
        self.assertEqual((inside.returncode, inside.stdout.strip()), (0, f"harness {VERSION}"), inside.stderr)
        lost = run(outside)  # outside every repository, the copy has no repository of its own
        self.assertEqual(lost.returncode, 1)
        self.assertIn("not inside a harness repository", lost.stderr)
        self.assertIn("HARNESS_HOME", lost.stderr)
        homed = run(outside, HARNESS_HOME=str(self.root))
        self.assertEqual((homed.returncode, homed.stdout.strip()), (0, f"harness {VERSION}"), homed.stderr)
        wrong = run(outside, HARNESS_HOME=str(outside))  # a folder that is no repository: the same message
        self.assertEqual(wrong.returncode, 1)
        self.assertIn("not inside a harness repository", wrong.stderr)
        stripped = os.environ.get("PATH", "").replace(str(Path.home() / "bin"), "")
        same = self.doctor(PATH=str(fixed) + os.pathsep + stripped)
        self.assertIn("是本仓库启动脚本的拷贝", same.stdout)
        self.assertNotIn("[WARN]  PATH 里的 `harness`", same.stdout)
        (fixed / "harness").write_text("#!/bin/sh\n# an old copy\n", encoding="utf-8")
        old = self.doctor(PATH=str(fixed) + os.pathsep + stripped)
        self.assertIn("[WARN]  PATH 里的 `harness`", old.stdout)
        self.assertIn("重新拷一份", old.stdout)

    def test_agent_facing_files_do_not_hard_code_python3(self) -> None:
        """Windows has `python` and often no `python3`. A command written with python3 must say it is for macOS/Linux."""
        offenders = []
        files = list((REPO / ".github").rglob("*.md")) + list((REPO / ".harness" / "contracts").rglob("*.md")) + [REPO / "README.md", REPO / ".workspace" / "README.md"]
        for path in files:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "python3 .harness/engine" in line and "macOS/Linux" not in line:
                    offenders.append(f"{path.relative_to(REPO)}:{number}")
        self.assertEqual(offenders, [])

    def test_the_cli_does_not_crash_on_a_terminal_that_cannot_show_chinese(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CLI), "eval", "show", "s4"], capture_output=True, check=False,
            env={**os.environ, "HARNESS_ROOT": str(REPO), "PYTHONIOENCODING": "ascii"},
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("ascii", "replace"))
        self.assertIn(b"\\u", result.stdout)

    # --- override ---------------------------------------------------------------------------

    def override(self, name: str, data: dict) -> None:
        (self.root / ".harness" / "policies" / f"{name}.override.json").write_text(json.dumps(data), encoding="utf-8")

    def test_no_override_file_is_said_in_one_line(self) -> None:
        self.assertIn("没有 override 文件", self.doctor().stdout)

    def test_an_override_lists_what_it_changed_and_where_each_value_comes_from(self) -> None:
        self.override("gate", {"guardrail_paths+": ["secrets/**"], "circuit_breaker": {"repeat_limit": 5}})
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("gate.override.json：改了 2 处", result.stdout)
        self.assertIn("来自 override：guardrail_paths（追加）", result.stdout)
        self.assertIn("来自 override：circuit_breaker.repeat_limit（替换）", result.stdout)

    def test_replacing_a_whole_array_is_a_warning_that_names_the_plus_form(self) -> None:
        self.override("gate", {"cli_owned_paths": ["x/**"]})
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("整体替换了默认的数组", result.stdout)
        self.assertIn('"cli_owned_paths+"', result.stdout)

    def test_an_override_that_drops_a_core_guardrail_is_an_error(self) -> None:
        self.override("gate", {"guardrail_paths": ["docs/**"]})
        result = self.doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("core guardrails cannot be removed", result.stdout)

    def test_an_override_with_no_policy_to_override_is_an_error(self) -> None:
        self.override("nothing", {"a": 1})
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("找不到它要覆盖的 nothing.json", result.stdout)

    def test_an_override_of_an_override_is_an_error(self) -> None:
        self.override("gate", {"circuit_breaker": {"repeat_limit": 5}})
        (self.root / ".harness" / "policies" / "gate.override.override.json").write_text("{}", encoding="utf-8")
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("只有一层", result.stdout)

    def test_a_plus_key_on_a_non_array_is_an_error(self) -> None:
        self.override("gate", {"l3_write_root+": ["x"]})
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("needs an array", result.stdout)

    # --- knowledge base ---------------------------------------------------------------------

    def kb(self, files: dict) -> None:
        for name, text in files.items():
            path = self.root / "knowledge-base" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def kb_instructions(self, text: str) -> None:
        path = self.root / ".github" / "instructions" / "knowledgebase.instructions.md"
        path.write_text(text, encoding="utf-8")

    def test_an_empty_knowledge_base_is_fine(self) -> None:
        self.kb({"README.md": "# KB\n"})
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("还没有内容", result.stdout)

    def test_a_knowledge_base_without_instructions_is_a_warning(self) -> None:
        self.kb({"README.md": "# KB\n- [a](a/x.md)\n", "a/x.md": "text\n"})
        self.kb_instructions("")  # the copy of this repository's file may have content while a knowledge base is plugged in
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("没有讲知识库的指令文件", result.stdout)

    def test_instructions_with_a_broad_apply_to_are_loaded(self) -> None:
        self.kb({"README.md": "# KB\n- [a](a/x.md)\n", "a/x.md": "text\n"})
        self.kb_instructions("---\napplyTo: '**'\n---\n按 knowledge-base/README.md 的索引读。\n")
        result = self.doctor()
        self.assertIn("会被加载（applyTo 是 **）", result.stdout)
        self.assertNotIn("[WARN]", result.stdout)

    def test_instructions_linked_from_agents_md_are_loaded(self) -> None:
        self.kb({"README.md": "# KB\n", "a.md": "text\n"})
        self.kb_instructions("---\napplyTo: 'knowledge-base/**'\n---\n按知识库索引读。\n")
        (self.root / "AGENTS.md").write_text("读知识库先看 [规则](.github/instructions/knowledgebase.instructions.md)。\n", encoding="utf-8")
        self.assertIn("AGENTS.md 里有链接", self.doctor().stdout)

    def test_instructions_that_only_apply_inside_the_knowledge_base_are_a_warning(self) -> None:
        self.kb({"README.md": "# KB\n", "a.md": "text\n"})
        self.kb_instructions("---\napplyTo: 'knowledge-base/**'\n---\n按知识库索引读。\n")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("没有让 Copilot 加载它的条件", result.stdout)

    def test_empty_instructions_do_not_count(self) -> None:
        self.kb({"README.md": "# KB\n", "a.md": "text\n"})
        self.kb_instructions("---\napplyTo: '**'\n---\n")
        self.assertIn("没有讲知识库的指令文件", self.doctor().stdout)

    def test_a_knowledge_base_without_a_readme_is_a_warning(self) -> None:
        self.kb({"a.md": "text\n"})
        self.assertIn("没有 README.md", self.doctor().stdout)

    def test_broken_links_in_the_index_are_a_warning(self) -> None:
        self.kb({"README.md": "# KB\n- [ok](a.md)\n- [gone](b/c.md)\n- [web](https://example.com/x)\n- [top](#top)\n", "a.md": "x\n"})
        result = self.doctor()
        self.assertIn("指向不存在文件的链接：b/c.md", result.stdout)
        self.assertNotIn("a.md,", result.stdout)

    def test_a_git_ignored_knowledge_base_is_a_warning(self) -> None:
        self.kb({"README.md": "# KB\n", "a.md": "text\n"})
        (self.root / ".gitignore").write_text("node_modules/\n/knowledge-base/\n", encoding="utf-8")
        self.assertIn(".gitignore 忽略了 knowledge-base/", self.doctor().stdout)

    def test_many_session_logs_are_a_warning_that_names_the_prune_command(self) -> None:
        self.edit_json(".harness/policies/observe.json", lambda data: data.update(warn_session_files=2))
        folder = self.root / ".harness" / "runtime" / "logs" / "vscode"
        folder.mkdir(parents=True)
        for name in ("a", "b", "c"):
            (folder / f"{name}.jsonl").write_text("{}\n", encoding="utf-8")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("logs prune", result.stdout)

    def test_the_old_shared_call_log_is_a_warning(self) -> None:
        folder = self.root / ".harness" / "runtime" / "logs"
        folder.mkdir(parents=True)
        (folder / "hook-calls.jsonl").write_text("{}\n", encoding="utf-8")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("hook-calls.jsonl", result.stdout)

    def test_a_bad_registry_is_an_error(self) -> None:
        self.edit_json(".harness/registry.json", lambda data: data["modules"]["task_level"].update(events=["NotAnEvent"]))
        self.assertEqual(self.doctor().returncode, 1)

    def test_a_missing_registry_is_an_error(self) -> None:
        (self.root / ".harness" / "registry.json").unlink()
        self.assertEqual(self.doctor().returncode, 1)

    def test_a_gate_policy_without_a_core_guardrail_is_an_error(self) -> None:
        self.edit_json(".harness/policies/gate.json", lambda data: data["guardrail_paths"].remove(".harness/engine/**"))
        result = self.doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("gate.json 有问题", result.stdout)

    def test_a_disabled_module_is_not_asked_for_events(self) -> None:
        def registry(data: dict) -> None:
            data["modules"]["task_level"]["events"].append("PostToolUse")
            data["modules"]["task_level"]["enabled"] = False

        def hooks(data: dict) -> None:
            data["hooks"]["PostToolUse"] = data["hooks"]["Stop"]

        self.edit_json(".harness/registry.json", registry)
        self.edit_json(".github/hooks/harness.json", hooks)
        result = self.doctor()
        self.assertIn("[WARN]", result.stdout)  # PostToolUse is no longer needed by the hook config
        self.assertIn("PostToolUse", result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout)


class LayoutTests(unittest.TestCase):
    def test_engine_code_parses_as_python_39(self) -> None:
        for path in sorted(ENGINE.rglob("*.py")):
            with self.subTest(path.relative_to(REPO).as_posix()):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))

    def test_engine_code_uses_only_the_standard_library(self) -> None:
        local = {"core", "adapters", "modules", "doctor", "hook", "cli"}
        stdlib = {
            "__future__", "argparse", "ast", "contextlib", "copy", "ctypes", "dataclasses", "datetime", "difflib", "hashlib", "importlib",
            "json", "locale", "math", "os", "pathlib", "posixpath", "random", "re", "shutil", "stat", "string", "subprocess", "sys", "tempfile", "time",
            "traceback", "typing", "urllib", "uuid",
        }
        for path in sorted(ENGINE.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module.split(".")[0]]
                for name in names:
                    with self.subTest(f"{path.name}: {name}"):
                        self.assertTrue(name in local or name in stdlib, name)

    def test_modules_import_only_core(self) -> None:
        """00 section 8.3: a module depends on core/ and on itself, never on another module or on adapters."""
        for path in sorted((ENGINE / "modules").rglob("*.py")):
            own = path.relative_to(ENGINE / "modules").parts[0]
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    root = node.module.split(".")[0]
                    with self.subTest(f"{path.name}: {node.module}"):
                        self.assertFalse(root in {"adapters", "hook", "cli", "doctor"}, node.module)
                        if root == "modules":
                            self.assertEqual(node.module.split(".")[1], own)

    def test_there_is_exactly_one_hook_config_and_the_old_files_are_gone(self) -> None:
        self.assertEqual([p.name for p in (REPO / ".github" / "hooks").glob("*.json")], ["harness.json"])
        for gone in (".tests", ".harness/task-policy", ".github/skills/task-level-policy"):
            self.assertFalse((REPO / gone).exists(), gone)

    def test_skill_directory_names_match_their_name_field_and_use_a_known_prefix(self) -> None:
        for skill in sorted((REPO / ".github" / "skills").glob("*/SKILL.md")):
            text = skill.read_text(encoding="utf-8")
            name = next(line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("name:"))
            with self.subTest(skill.parent.name):
                self.assertEqual(name, skill.parent.name)
                self.assertTrue(name.startswith(("harness-", "generic-", "domain-")) or name in LEVEL_ENTRY_SKILLS or name == "typesafe-ai", name)


if __name__ == "__main__":
    unittest.main()
