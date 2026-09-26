"""Discovery bridge for the hyphenated tests/task-policy fixture directory."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str) -> unittest.TestSuite:
    path = Path(__file__).parent / "task-policy" / "test_task_policy.py"
    specification = importlib.util.spec_from_file_location("task_policy_fixtures", path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Unable to load Task Level tests from {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return loader.loadTestsFromModule(module)
