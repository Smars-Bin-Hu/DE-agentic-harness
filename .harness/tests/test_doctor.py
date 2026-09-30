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
    ignore = shutil.ignore_patterns("__pycache__", "runtime", "*.pyc")
    shutil.copytree(REPO / ".github", destination / ".github", ignore=ignore)
    shutil.copytree(REPO / ".harness", destination / ".harness", ignore=ignore)


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        copy_repo(self.root)

    def doctor(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLI), "doctor"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            env={**os.environ, "HARNESS_ROOT": str(self.root)},
            check=False,
        )

    def edit_json(self, relative: str, change) -> None:
        path = self.root / relative
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_a_clean_copy_passes(self) -> None:
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("[ERROR]", result.stdout)

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
            data["levels"]["1"]["execution_budget"]["repository_searches"] = "two"

        self.edit_json(".harness/policies/task-levels.json", change)
        result = self.doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn("task-levels.json", result.stdout)

    def test_a_broken_override_is_caught_by_the_same_check(self) -> None:
        (self.root / ".harness" / "policies" / "task-levels.override.json").write_text(
            json.dumps({"levels": {"2": {"subagents": {"allowed": "yes"}}}}), encoding="utf-8"
        )
        self.assertEqual(self.doctor().returncode, 1)

    def test_a_bad_registry_is_an_error(self) -> None:
        self.edit_json(".harness/registry.json", lambda data: data["modules"]["task_level"].update(events=["NotAnEvent"]))
        self.assertEqual(self.doctor().returncode, 1)

    def test_a_missing_registry_is_an_error(self) -> None:
        (self.root / ".harness" / "registry.json").unlink()
        self.assertEqual(self.doctor().returncode, 1)

    def test_a_disabled_module_is_not_asked_for_events(self) -> None:
        def change(data: dict) -> None:
            data["modules"]["task_level"]["enabled"] = False

        self.edit_json(".harness/registry.json", change)
        result = self.doctor()
        self.assertIn("[WARN]", result.stdout)  # its events are no longer needed by the hook config
        self.assertEqual(result.returncode, 0, result.stdout)


class LayoutTests(unittest.TestCase):
    def test_engine_code_parses_as_python_39(self) -> None:
        for path in sorted(ENGINE.rglob("*.py")):
            with self.subTest(path.relative_to(REPO).as_posix()):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))

    def test_engine_code_uses_only_the_standard_library(self) -> None:
        local = {"core", "adapters", "modules", "doctor", "hook", "cli"}
        stdlib = {
            "__future__", "argparse", "contextlib", "copy", "dataclasses", "datetime", "hashlib", "importlib",
            "json", "math", "os", "pathlib", "re", "sys", "tempfile", "time", "traceback", "typing", "uuid",
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
                self.assertTrue(name.startswith(("harness-", "generic-", "domain-")) or name == "typesafe-ai", name)


if __name__ == "__main__":
    unittest.main()
