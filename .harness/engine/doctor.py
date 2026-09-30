"""`cli.py doctor`: check that registry, files, hook config, policies and tool kinds agree."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from core import config
from core.registry import load_registry
from core.state import TRACKED_EVENTS

HOOK_ENTRY = ".harness/engine/hook.py"
COMMAND_KEYS = ("command", "windows", "linux", "osx", "bash", "powershell")
TOOL_KINDS = {"read", "edit", "create", "terminal", "search", "subagent", "mcp"}


class Report:
    def __init__(self) -> None:
        self.errors = 0
        self.lines: List[str] = []

    def ok(self, message: str) -> None:
        self.lines.append(f"[OK]    {message}")

    def warn(self, message: str) -> None:
        self.lines.append(f"[WARN]  {message}")

    def error(self, message: str) -> None:
        self.errors += 1
        self.lines.append(f"[ERROR] {message}")


def check_python(report: Report) -> None:
    version = sys.version_info
    text = f"{version.major}.{version.minor}.{version.micro}"
    if version >= (3, 9):
        report.ok(f"Python {text}")
    else:
        report.error(f"Python {text} 太旧，需要 3.9 或更高")


def check_files(report: Report, root: Path, owner: str, files: List[str]) -> None:
    missing = [name for name in files if not (root / name).exists()]
    for name in missing:
        report.error(f"{owner}：登记的文件不存在：{name}")
    if not missing:
        report.ok(f"{owner}：{len(files)} 个登记文件都存在")


def check_hook_config(report: Report, root: Path, registry: Dict[str, Any]) -> None:
    directory = root / ".github" / "hooks"
    configs = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not configs:
        report.error("没有 hook 配置：.github/hooks/*.json")
        return
    if len(configs) > 1:
        names = ", ".join(path.name for path in configs)
        report.error(f"有 {len(configs)} 个 hook 配置（{names}）。同一事件会被执行多次，只保留一份")
    configured: Set[str] = set()
    for path in configs:
        try:
            data = config.read_json(path)
            hooks = data["hooks"]
        except Exception as error:
            report.error(f"{path.name} 不能解析：{error}")
            continue
        for event, entries in hooks.items():
            configured.add(event)
            for entry in entries:
                commands = [entry[key] for key in COMMAND_KEYS if isinstance(entry.get(key), str)]
                if not commands or any(HOOK_ENTRY not in command for command in commands):
                    report.error(f"{path.name} 的 {event} 没有指向 {HOOK_ENTRY}")
    needed: Set[str] = set(TRACKED_EVENTS)
    for name, entry in registry["modules"].items():
        if entry["enabled"] and entry["status"] != "retired":
            needed.update(entry["events"])
    for event in sorted(needed - configured):
        report.error(f"hook 配置缺少事件 {event}（core 或模块需要它）")
    for event in sorted(configured - needed):
        report.warn(f"hook 配置里的 {event} 没有模块订阅，白白多启动一个进程")
    if configured >= needed:
        report.ok(f"hook 配置指向 hook.py，覆盖 {len(configured & needed)} 个需要的事件")


def check_module(report: Report, root: Path, name: str, entry: Dict[str, Any]) -> None:
    if entry["status"] == "retired":
        return
    check_files(report, root, f"模块 {name}", entry["files"])
    try:
        module = importlib.import_module(f"modules.{name}")
        if not callable(getattr(module, "handle", None)):
            raise AttributeError("没有 handle(event, ctx)")
    except Exception as error:
        (report.error if entry["enabled"] else report.warn)(f"模块 {name} 不能加载：{error}")
        return
    report.ok(f"模块 {name} 可以加载")
    policy_name = getattr(module, "POLICY_NAME", None)
    if policy_name:
        try:
            module.validate_policy(config.load_policy(root, policy_name))
            report.ok(f"策略 {policy_name}.json 正常")
        except Exception as error:
            report.error(f"策略 {policy_name}.json 有问题：{error}")


def check_tool_kinds(report: Report) -> None:
    path = Path(__file__).resolve().parent / "adapters" / "tool_kinds.json"
    try:
        data = config.read_json(path)
        bad = [
            f"{surface}:{tool}={kind}"
            for surface, body in data["surfaces"].items()
            for tool, kind in body["tools"].items()
            if kind not in TOOL_KINDS
        ]
    except Exception as error:
        report.error(f"tool_kinds.json 不能解析：{error}")
        return
    if bad:
        report.error("tool_kinds.json 有未知的类别：" + ", ".join(bad))
    else:
        report.ok("tool_kinds.json 正常")


def run(root: Path) -> int:
    report = Report()
    check_python(report)
    try:
        registry = load_registry(root)
    except Exception as error:
        report.error(f"registry.json 不能读取：{error}")
        print("\n".join(report.lines))
        return 1
    report.ok("registry.json 正常")
    check_files(report, root, "engine", registry["engine"]["files"])
    check_tool_kinds(report)
    check_hook_config(report, root, registry)
    for name, entry in registry["modules"].items():
        check_module(report, root, name, entry)
    print("\n".join(report.lines))
    print(json.dumps({"errors": report.errors}))
    return 1 if report.errors else 0
