"""`cli.py doctor`: check that registry, files, hook config, policies and tool kinds agree."""

from __future__ import annotations

import ast
import importlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from core import config, output, targets
from core.paths import cli_command, policies_dir, python_command
from core.registry import load_registry
from core.state import TRACKED_EVENTS

HOOK_ENTRY = ".harness/engine/hook.py"
COMMAND_KEYS = ("command", "windows", "linux", "osx", "bash", "powershell")
KB_DIR = "knowledge-base"
KB_IGNORED = {"README.md", ".gitkeep", ".gitignore", ".DS_Store"}
BROAD_APPLY_TO = {"**", "**/*", "*", "**/**"}
MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
SHOWN_BROKEN_LINKS = 5
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


def check_interpreter(report: Report) -> None:
    """The commands shown to agents start with `python` (Windows) or `python3` (elsewhere). It has to run from the terminal."""
    name = python_command()
    if shutil.which(name):
        report.ok(f"终端里能找到 `{name}`（agent 提示里的命令前缀：{cli_command()}）")
    else:
        report.warn(f"终端的 PATH 里找不到 `{name}`。agent 提示里的命令前缀是 `{cli_command()}`，运行会失败。装好 Python，或把它加进 PATH")


def check_files(report: Report, root: Path, owner: str, files: List[str]) -> None:
    missing = [name for name in files if not (root / name).exists()]
    for name in missing:
        report.error(f"{owner}：登记的文件不存在：{name}")
    if not missing:
        report.ok(f"{owner}：{len(files)} 个登记文件都存在")


def interpreter_problems(entry: Dict[str, Any]) -> List[str]:
    """Each runtime reads its own keys: VS Code `command`/`windows`, the Copilot CLI engine `bash`/`powershell`.

    An engine that finds no key for its system runs the wrong one, and the CLI engine treats a hook that fails as a deny:
    every tool call is refused. Windows has `python` and often no `python3`.
    """
    problems = []
    for key, interpreter in (("command", "python3"), ("bash", "python3"), ("windows", "python"), ("powershell", "python")):
        value = entry.get(key)
        if not isinstance(value, str):
            problems.append(f"缺少 `{key}`（{'Windows' if interpreter == 'python' else 'macOS/Linux'} 上的 {'VS Code' if key in ('command', 'windows') else 'Copilot CLI 引擎'} 读它）")
        elif value.split()[0] != interpreter:
            problems.append(f"`{key}` 应该用 `{interpreter}`，现在是 `{value.split()[0]}`")
    return problems


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
                for problem in interpreter_problems(entry):
                    report.error(f"{path.name} 的 {event}：{problem}")
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
    own_check = getattr(module, "doctor", None)
    if callable(own_check):
        found = own_check(root)
        for text in found:
            report.error(f"模块 {name}：{text}")
        if not found:
            report.ok(f"模块 {name} 自己的检查通过")
    policy_name = getattr(module, "POLICY_NAME", None)
    if policy_name:
        try:
            module.validate_policy(config.load_policy(root, policy_name))
            report.ok(f"策略 {policy_name}.json 正常")
        except Exception as error:
            report.error(f"策略 {policy_name}.json 有问题：{error}")


def check_logs(report: Report, root: Path, registry: Dict[str, Any]) -> None:
    """Nothing deletes the session logs by itself. Say so when there are many, and name the command."""
    entry = registry["modules"].get("observe")
    if entry is None or not entry["enabled"]:
        return
    try:
        limit = config.load_policy(root, "observe")["warn_session_files"]
    except Exception:
        return  # the policy check of the module reports a broken file
    base = root / ".harness" / "runtime" / "logs"
    count = len(list(base.glob("*/*.jsonl"))) if base.is_dir() else 0
    if count > limit:
        report.warn(f"有 {count} 个会话日志（超过 {limit}）。不用的可以删：{cli_command()} logs prune --days 30")
    if (base / "hook-calls.jsonl").exists():
        report.warn("还有旧的 .harness/runtime/logs/hook-calls.jsonl。现在每个会话一个文件，这个旧文件不再写入，可以删除")


def check_output(report: Report, root: Path) -> bool:
    """How the CLI prints Chinese here. Returns True when the raw UTF-8 sample line should be printed too."""
    try:
        raw = config.load_policy(root, output.POLICY_NAME)["output"]["encoding"]
    except Exception as error:
        report.error(f"cli.json 不能读取或缺 output.encoding：{error}")
        return False
    if raw not in output.CHOICES:
        report.error(f"cli.json 的 output.encoding 是 `{raw}`，只能是 {'、'.join(output.CHOICES)}。现在按 auto 处理")
    facts = output.facts()
    pages = facts["code_pages"]
    where = "终端" if facts["terminal"] else "管道或重定向"
    shown = f"输出编码：stdout={facts['stdout_encoding']}（{where}），系统默认={facts['preferred']}"
    if pages:
        shown += f"，代码页 输出={pages['console_output']} ANSI={pages['ansi']}"
    shown += f"；output.encoding={output.setting(root)}"
    if output.shows(output.SAMPLE, facts["stdout_encoding"]):
        report.ok(shown)
        report.ok(f"  {output.SAMPLE}（这一行能读，中文输出就正常）")
        return False
    report.warn(shown + "。这个编码写不出中文，CLI 的中文会显示成 \\uXXXX")
    return True


def print_utf8_sample() -> None:
    """One line as raw UTF-8 bytes, whatever the stream encoding is: it shows what `output.encoding: utf-8` would look like here.

    The advice is in that line too: a person who can read it is a person for whom the switch works.
    """
    text = (
        f"[INFO]  UTF-8 样例：{output.SAMPLE}。这一行能读，就新建 .harness/policies/cli.override.json，"
        '写 {"output": {"encoding": "utf-8"}}，CLI 的中文就不再是 \\uXXXX；这一行是乱码，就不要改。\n'
    )
    try:
        sys.stdout.flush()
        sys.stdout.buffer.write(text.encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception:  # noqa: BLE001 - a sample line must not fail doctor
        pass


def check_overrides(report: Report, root: Path) -> None:
    """Each `<name>.override.json`: one layer, merges onto an existing policy, and says what it changed."""
    directory = policies_dir(root)
    found = sorted(directory.glob("*" + config.OVERRIDE_SUFFIX)) if directory.is_dir() else []
    if not found:
        report.ok("没有 override 文件，所有策略都用默认值")
        return
    for path in found:
        name = path.name[: -len(config.OVERRIDE_SUFFIX)]
        if config.OVERRIDE_SUFFIX[:-5] in name or not (directory / f"{name}.json").exists():
            report.error(f"{path.name}：找不到它要覆盖的 {name}.json（override 只有一层，名字必须是 <策略名>.override.json）")
            continue
        try:
            base = config.read_json(directory / f"{name}.json")
            override = config.read_json(path)
            config.deep_merge(base, override)
        except Exception as error:
            report.error(f"{path.name}：不能合并到 {name}.json：{error}")
            continue
        touched = config.changes(base, override)
        report.ok(f"{path.name}：改了 {len(touched)} 处，其余都来自 {name}.json（default）")
        for where, how, size in touched:
            if how == "replaced" and size:
                report.warn(f"{path.name}：{where} 整体替换了默认的数组（{size} 项）。要保留默认项，改用 \"{where.split('.')[-1]}+\" 追加")
            else:
                report.ok(f"  来自 override：{where}（{ {'replaced': '替换', 'appended': '追加', 'added': '新增'}[how] }）")


def front_matter(text: str) -> Dict[str, str]:
    front = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not front:
        return {}
    pairs = (line.split(":", 1) for line in front.group(1).splitlines() if ":" in line)
    return {key.strip(): value.strip().strip("'\"") for key, value in pairs}


def body_of(text: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n?", "", text, count=1, flags=re.DOTALL).strip()


def kb_instruction_files(root: Path) -> List[Path]:
    """Instruction files that have text and are about the knowledge base: named after it, or naming its folder."""
    directory = root / ".github" / "instructions"
    found = []
    for path in sorted(directory.glob("*.instructions.md")) if directory.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        if body_of(text) and ("knowledge" in path.name.lower() or KB_DIR in text.lower()):
            found.append(path)
    return found


def kb_instruction_loads(root: Path, path: Path) -> str:
    """Why Copilot would load the file on its own, or an empty string when nothing makes it."""
    apply_to = front_matter(path.read_text(encoding="utf-8")).get("applyTo", "")
    if any(part.strip() in BROAD_APPLY_TO for part in apply_to.split(",")):
        return f"applyTo 是 {apply_to}"
    for name in ("AGENTS.md", ".github/copilot-instructions.md"):
        entry = root / name
        if entry.is_file() and path.name in entry.read_text(encoding="utf-8"):
            return f"{name} 里有链接"
    return ""


def kb_broken_links(kb: Path) -> List[str]:
    readme = kb / "README.md"
    broken = []
    for target in MARKDOWN_LINK.findall(readme.read_text(encoding="utf-8")):
        target = target.split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or target.startswith("/"):
            continue
        if not (kb / target).exists():
            broken.append(target)
    return broken


def kb_git_ignored(root: Path) -> bool:
    ignore = root / ".gitignore"
    if not ignore.is_file():
        return False
    names = {KB_DIR, f"/{KB_DIR}", f"{KB_DIR}/", f"/{KB_DIR}/", f"{KB_DIR}/*", f"/{KB_DIR}/*", f"{KB_DIR}/**", f"/{KB_DIR}/**"}
    return any(line.strip() in names for line in ignore.read_text(encoding="utf-8").splitlines())


def check_knowledge_base(report: Report, root: Path) -> None:
    """Can an agent reach the knowledge base? Looks at the folder, its README index and the instructions. Warns only."""
    kb = root / KB_DIR
    content = [item for item in sorted(kb.iterdir()) if item.name not in KB_IGNORED and not item.name.startswith(".")] if kb.is_dir() else []
    if not content:
        report.ok(f"{KB_DIR}/ 里还没有内容（没有接入知识库）")
        return
    report.ok(f"{KB_DIR}/ 有内容：{len(content)} 项（README 以外）")
    if not (kb / "README.md").is_file():
        report.warn(f"{KB_DIR}/ 没有 README.md。agent 按索引渐进读取时，没有入口可读")
    else:
        broken = kb_broken_links(kb)
        shown = ", ".join(broken[:SHOWN_BROKEN_LINKS]) + (f" 等 {len(broken)} 个" if len(broken) > SHOWN_BROKEN_LINKS else "")
        if broken:
            report.warn(f"{KB_DIR}/README.md 里有指向不存在文件的链接：{shown}")
        else:
            report.ok(f"{KB_DIR}/README.md 的相对链接都能找到文件")
    if kb_git_ignored(root):
        report.warn(f".gitignore 忽略了 {KB_DIR}/。Copilot 的搜索会跳过被忽略的文件，agent 可能搜不到它（按路径直接读一般不受影响）")
    files = kb_instruction_files(root)
    if not files:
        report.warn("没有讲知识库的指令文件。把知识库自带的 instructions 放到 .github/instructions/（例如 knowledgebase.instructions.md），agent 才知道怎么按索引读")
        return
    for path in files:
        reason = kb_instruction_loads(root, path)
        if reason:
            report.ok(f"{path.name} 讲知识库，而且会被加载（{reason}）")
        else:
            report.warn(
                f"{path.name} 讲知识库，但没有让 Copilot 加载它的条件。给它写 applyTo: '**'，或在 AGENTS.md 里放一个指向它的链接；"
                "只写 applyTo: 'knowledge-base/**' 不够：agent 读到知识库文件之前，它不会生效"
            )


def check_targets(report: Report, root: Path) -> None:
    """The target repositories (target.json + target.override.json): found, git repositories, with their base branch."""
    try:
        found = targets.load(root)
    except Exception as error:
        report.error(f"策略 target.json 有问题：{error}")
        return
    if not found.configured:
        report.ok("没有配置目标仓库（target.override.json 里写 repos_root），请求沿用 harness 自己的仓库")
        return
    for problem in found.problems:
        report.error(f"目标仓库：{problem}")
    if not found.repos:
        if not found.problems:
            report.warn("repos_root 下没有 git 仓库（要有 .git 的子文件夹）")
        return
    for name in found.names():
        repo = found.repos[name]
        try:
            info = targets.summary(repo, found.timeout)
        except targets.TargetError as error:
            report.error(f"目标仓库 {name}：{error}")
            continue
        if not info["has_base_ref"]:
            report.error(f"目标仓库 {name}：本地没有分支 `{repo.base_ref}`。先在那个仓库里 git switch 或 git fetch 一次，或在 target.override.json 的 repos 里改 base_ref")
            continue
        state = "工作区干净" if info["clean"] else f"有 {info['uncommitted_files']} 个未提交的文件（promote 要求工作区干净）"
        report.ok(f"目标仓库 {name}：{repo.base_ref} 在 {info['base_commit']}（{info['base_commit_date'][:10]}），当前分支 {info['current_branch']}，{state}")


def check_location(report: Report, root: Path) -> None:
    problems = targets.location_warnings(str(root))
    for text in problems:
        report.warn(text)
    if not problems:
        report.ok("harness 的路径长度和位置没有问题")


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


def agent_models(path: Path) -> Any:
    """The `model` line of an .agent.md front matter: a list of names, a single name, or None when there is none."""
    text = path.read_text(encoding="utf-8")
    front = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not front:
        return None
    for line in front.group(1).splitlines():
        if line.startswith("model:"):
            value = line.split(":", 1)[1].strip()
            if not value:
                return None
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return [value.strip("'\"")]
            return parsed if isinstance(parsed, list) else [str(parsed)]
    return None


def series_of(name: str, series: Dict[str, List[str]]) -> str:
    lowered = name.lower()
    for label, words in series.items():
        if any(word.lower() in lowered for word in words):
            return label
    return ""


def check_agents(report: Report, root: Path) -> None:
    """Each agent's model list stays in one series (unless it is in `any_series`); roles listed in `different_series` do not share one."""
    directory = root / ".github" / "agents"
    if not directory.is_dir() or not (root / ".harness" / "policies" / "agents.json").exists():
        return
    try:
        policy = config.load_policy(root, "agents")
    except Exception as error:
        report.error(f"策略 agents.json 不能读取：{error}")
        return
    chosen: Dict[str, str] = {}
    for path in sorted(directory.glob("*.agent.md")):
        agent = path.name[: -len(".agent.md")]
        names = agent_models(path)
        if not names:
            continue
        labels = {series_of(name, policy["series"]) for name in names}
        if "" in labels:
            report.warn(f"agent {agent} 的 model 里有不认识的模型名：{', '.join(n for n in names if not series_of(n, policy['series']))}。在 agents.json 里加系列关键词，或检查拼写")
            labels.discard("")
        if len(labels) > 1 and agent in policy.get("any_series", []):
            continue  # this agent may fall back across series; it takes no part in `different_series`
        if len(labels) > 1:
            report.error(f"agent {agent} 的 model 回退列表跨了系列（{', '.join(sorted(labels))}）。回退只能在同一系列里")
        elif labels:
            chosen[agent] = next(iter(labels))
    for group in policy.get("different_series", []):
        present = [name for name in group if name in chosen]
        seen: Dict[str, str] = {}
        for name in present:
            if chosen[name] in seen:
                report.error(f"agent {seen[chosen[name]]} 和 {name} 用了同一系列（{chosen[name]}），必须不同系列")
            seen[chosen[name]] = name
    report.ok(f"agent 的模型系列检查完成（{len(chosen)} 个 agent）")


def run(root: Path) -> int:
    report = Report()
    check_python(report)
    check_interpreter(report)
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
    check_agents(report, root)
    check_logs(report, root, registry)
    check_overrides(report, root)
    sample = check_output(report, root)
    check_targets(report, root)
    check_location(report, root)
    check_knowledge_base(report, root)
    for name, entry in registry["modules"].items():
        check_module(report, root, name, entry)
    print("\n".join(report.lines))
    if sample:
        print_utf8_sample()
    print(json.dumps({"errors": report.errors}))
    return 1 if report.errors else 0
