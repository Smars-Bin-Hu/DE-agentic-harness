"""What each request command does. Every function takes the repo root and returns a dict for the CLI to print.

A refusal raises CommandError with the reason and the next step. Files are copied, never retyped (design principle 5).
A package that was dispatched, and a handoff that was submitted, are made read-only: they do not change afterwards.
"""

from __future__ import annotations

import difflib
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, repo_paths, targets
from core.paths import cli_command, mkdir_command, utc_now
from core.state import admin_on, session, state_path

from . import brief as brief_module
from . import layout, store
from .layout import CommandError
from .policy import POLICY_NAME

PLACEHOLDER = "（待填）"
SKIP_NAMES = {".git", "__pycache__", "node_modules", ".DS_Store"}
STATUS_ENDS = ("accepted", "hitl", "abandoned")


def policy(root: Path) -> Dict[str, Any]:
    from .policy import validate_policy

    value = config.load_policy(root, POLICY_NAME)
    validate_policy(value)
    return value


def read_only(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    except OSError:
        pass


def writable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
    except OSError:
        pass


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        writable(path)
    path.write_text(text, encoding="utf-8")


def source_files(root: Path, raw: str) -> List[Path]:
    """Files named by one `--input` or `add-input` path: a file, or every file under a folder. Must be inside the repo."""
    path = Path(raw)
    path = path if path.is_absolute() else root / path
    if layout.inside(root, path) is None:
        raise CommandError(f"`{raw}` 在仓库之外，不能当输入。只能复制仓库里的文件。")
    if not path.exists():
        raise CommandError(f"`{raw}` 不存在。检查路径。")
    if path.is_file():
        return [path]
    found = []
    for current, folders, files in os.walk(str(path)):
        folders[:] = sorted(name for name in folders if name not in SKIP_NAMES)
        for name in sorted(files):
            if name not in SKIP_NAMES:
                found.append(Path(current) / name)
    return found


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        writable(destination)
    shutil.copyfile(str(source), str(destination))


def entry(root: Path, source: Path, destination: Path, package_part: Path, purpose: str) -> Dict[str, str]:
    """A manifest line: where the copy is (relative to the package), where it came from, and its hash."""
    return {
        "path": destination.relative_to(package_part).as_posix(),
        "source": layout.inside(root, source) or str(source),
        "purpose": purpose,
        "sha256": store.sha256_file(destination),
    }


def copy_in(root: Path, sources: List[str], target: Path, limit: int, purpose: str) -> List[Dict[str, str]]:
    """Copy files under `target/<repo-relative path>`. Returns manifest-style entries."""
    items = []
    for raw in sources:
        for file in source_files(root, raw):
            relative = layout.inside(root, file)
            if relative is None:
                raise CommandError(f"`{file}` 在仓库之外，不能当输入。")
            items.append((file, relative))
    if len(items) > limit:
        raise CommandError(f"一次复制了 {len(items)} 个文件，上限 {limit}。只复制这个任务要用的文件。")
    entries = []
    for file, relative in items:
        destination = target / relative
        copy_file(file, destination)
        entries.append(entry(root, file, destination, target.parent, purpose))
    return entries


# --- request new / show -----------------------------------------------------------------------------


TASKS_DIR = ".workspace/current_tasks"


def load_targets(root: Path) -> targets.Targets:
    try:
        return targets.load(root)
    except Exception as error:
        raise CommandError(f"目标仓库的配置有问题（target.json 或 target.override.json）：{error}") from error


def target_repo(found: targets.Targets, name: str) -> targets.Repo:
    try:
        return found.get(name)
    except targets.TargetError as error:
        raise CommandError(str(error)) from error


def clean_branch(branch: str) -> str:
    name = branch.strip()
    if name and not targets.valid_branch(name):
        raise CommandError(f"分支名 `{name}` 不合法。写成 `feature/<名字>`，名字只能用字母、数字和下划线，不能有 `-`、`.`、`/`。")
    return name


def clean_task(root: Path, raw: str) -> str:
    """A task folder under .workspace/current_tasks/, as a path relative to the repository. Empty when none is given."""
    text = raw.strip()
    if not text:
        return ""
    path = Path(text)
    path = path if path.is_absolute() else root / path
    relative = layout.inside(root, path)
    if relative is None or not relative.startswith(TASKS_DIR + "/"):
        raise CommandError(f"--task `{raw}` 要是 {TASKS_DIR}/ 下的一个任务目录，例如 {TASKS_DIR}/<任务名>。")
    if not path.is_dir():
        raise CommandError(f"任务目录 `{relative}` 不存在。")
    return relative


def target_note(data: Dict[str, Any], found: Optional[targets.Targets] = None, role: str = "builder") -> str:
    """One line for the assignment: this request changes files in target repositories, so output paths start with the repository."""
    if not data.get("target_mode"):
        return ""
    names = "、".join(found.names()) if found else ""
    known = f"可用的仓库：{names}。" if names else ""
    if role == "reviewer":
        return (
            "- 这个请求改的是目标仓库里的文件。先读 `candidate.diff`（成果和 main 的差异，只有改动的行）；需要完整内容时读 `candidate/<仓库名>/<路径>`，改动前 main 上的版本在 `base/<仓库名>/<路径>`（新文件没有）。被删除的文件在 `candidate.diff` 里标着 `deleted file`。"
            f"{known}"
        )
    return (
        "- 这个请求改的是目标仓库里的文件。要改的文件在输入包的 `inputs/<仓库名>/<路径>`（main 上的版本，只读）。"
        f"成果路径的第一段也是仓库名，例如 `bdtt_repo/src/a.sql`，`--output` 也这样写。要删除文件（包括改名、移动时的旧文件）：它必须是取过的文件，交接时用 `--delete <仓库名>/<路径>`，不要在成果里放空文件。{known}"
    )


def new_request(root: Path, title: str, session_id: str, surface: str = "vscode", task: str = "", branch: str = "") -> Dict[str, Any]:
    title = title.strip()
    if not title:
        raise CommandError("--title 不能为空。")
    found = load_targets(root)
    task_path, branch_name = clean_task(root, task), clean_branch(branch)
    if branch_name and not found.configured:
        raise CommandError("还没有配置目标仓库（target.override.json 里的 repos_root），--branch 用不上。")
    if not state_path(root, surface, session_id).exists():
        raise CommandError(
            f"没有会话 `{session_id}`。用本条提示开头规则里写的“当前会话 id”，原样抄，不要改。"
        )
    request_id = store.new_request_id(root, title)
    directory = layout.request_dir(root, request_id)
    with session(root, surface, session_id) as state:
        if admin_on(state):
            raise CommandError("这个会话在 admin 模式里，不能开 L3 请求。admin 只用来二开和排查 harness；做任务请用户换一个对话，或先运行 `admin off`。")
        if state["active_request"]:
            raise CommandError(
                f"这个会话已经有进行中的请求 `{state['active_request']}`。先用 `request set-status` 结束它，再建新的。"
            )
        try:
            for sub in (
                "orchestrator", "builder/.pending", "builder/outputs", "reviewer/outputs",
                "handoffs/orchestrator/init-inputs", "handoffs/builder", "handoffs/reviewer",
            ):
                (directory / sub).mkdir(parents=True)
            write_text(directory / "orchestrator" / "plan.md", f"# 计划：{title}\n\n（待填）\n")
            store.write_request(root, directory, store.empty_request(request_id, title, session_id, surface, found.configured, task_path, branch_name))
        except BaseException:
            shutil.rmtree(str(directory), ignore_errors=True)
            raise
        state["active_request"] = request_id
    result = {
        "request_id": request_id,
        "path": layout.REQUESTS_DIR + "/" + request_id,
        "next": "request add-input 放入需求和必要文件；写 knowledge-brief 后 brief set；写 orchestrator/plan.md；停下来请用户批准计划（`request approve-plan`，用户在终端运行）；批准后再 attempt new。",
    }
    if found.configured:
        result["target_repos"] = found.names()
        result["next"] += " 要改目标仓库里的文件，用 --from-target <仓库名>/<路径> 取 main 的版本；promote 之前要 `request set-branch`。"
    if task_path:
        result["task"] = task_path
    if branch_name:
        result["branch"] = branch_name
    return result


def set_branch(root: Path, request_id: str, branch: str) -> Dict[str, Any]:
    name = clean_branch(branch)
    if not name:
        raise CommandError("--branch 不能为空。")
    with store.locked(root, request_id) as data:
        store.require_open(data)
        if not data.get("target_mode"):
            raise CommandError("这个请求没有目标仓库，不需要分支名。")
        if data["promote"]["state"] == "done":
            raise CommandError("已经 promote 过了，分支名不能再改。")
        reset = data["promote"]["state"] == "dry_run"
        if reset:
            data["promote"] = {"state": "none"}  # the plan names the branch: a new name needs a new dry-run and a new approval
        data["branch"] = name
    return {"request_id": request_id, "branch": name, "promote_plan_reset": reset}


def list_requests(root: Path, status: str = "") -> Dict[str, Any]:
    """Every request folder, newest first: enough for a person to find a request id."""
    found: List[Dict[str, Any]] = []
    base = layout.requests_root(root)
    for path in base.iterdir() if base.is_dir() else []:
        try:
            data = store.read_request(root, path.name)
        except Exception:
            continue  # a folder that is not a request; `check` is the tool for a broken one
        if status and data["status"] != status:
            continue
        from . import planapproval  # it imports this module

        plan = planapproval.plan_path(root, path.name)
        found.append({
            "plan_ready": plan.is_file() and PLACEHOLDER not in plan.read_text(encoding="utf-8", errors="replace"),
            "plan_approved": planapproval.approved(root, path.name, data),
            "request_id": data["request_id"], "title": data["title"], "status": data["status"],
            "attempt": data["attempt"], "promote": data["promote"]["state"],
            "waiting_for_approval": data["status"] == "open" and data["promote"]["state"] == "dry_run" and "approved_plan_sha256" not in data["promote"],
            "waiting_for": (data.get("waiting") or {}).get("reason", ""),
            "created_at": data["created_at"],
        })
    found.sort(key=lambda item: item["created_at"], reverse=True)  # the id starts with the minute only; the time is exact
    return {"requests": found}


def show(root: Path, request_id: str) -> Dict[str, Any]:
    return store.read_request(root, request_id)


# --- inputs and brief -------------------------------------------------------------------------------


def any_dispatched(data: Dict[str, Any]) -> bool:
    return any(item["dispatched"] for item in data["attempts"])


def copy_from_target(
    root: Path, data: Dict[str, Any], specs: List[str], target: Path, limit: int, purpose: str
) -> List[Dict[str, str]]:
    """Files of target repositories as `base_ref` has them (the commit is fixed at the first read), not the working tree.

    A spec is `<repo>/<path>`: a file, or a folder (every tracked file under it). Records the repositories and the blob
    of each file in `data`, so promote can tell later whether main moved under the files it is about to write.
    """
    if not specs:
        return []
    found = load_targets(root)
    if not found.configured:
        raise CommandError("还没有配置目标仓库。在 .harness/policies/target.override.json 里写 repos_root，运行 `target list` 确认。")
    records = data.setdefault("targets", {})
    files = data.setdefault("target_files", {})
    wanted: Dict[str, Any] = {}
    for spec in specs:
        name, _, rest = spec.strip().replace("\\", "/").partition("/")
        if not name or not rest.strip("/"):
            raise CommandError(f"--from-target `{spec}` 要写成 `<仓库名>/<仓库里的路径>`，例如 bdtt_repo/src/a.sql。")
        repo = target_repo(found, name)
        relative = layout.relative_name(rest, "仓库里的路径")
        if name not in records:
            try:
                commit = targets.ref_commit(repo, found.timeout)
            except targets.TargetError as error:
                raise CommandError(str(error)) from error
            if not commit:
                raise CommandError(f"仓库 {name} 本地没有分支 `{repo.base_ref}`。先在那个仓库里准备好它，运行 `doctor` 确认。")
            records[name] = {"path": str(repo.path), "base_ref": repo.base_ref, "base_commit": commit}
        commit = records[name]["base_commit"]
        try:
            listed = targets.tracked_files(repo, commit, relative, found.timeout)
        except targets.TargetError as error:
            raise CommandError(str(error)) from error
        if not listed:
            raise CommandError(f"仓库 {name} 的 {repo.base_ref}（{commit[:12]}）上没有 `{relative}`。要新建的文件不用取，让 builder 在成果里创建。")
        for mode, blob, path in listed:
            if mode not in targets.REGULAR_FILE_MODES:
                if path == relative:
                    raise CommandError(f"`{name}/{path}` 不是普通文件（符号链接或子模块），不能复制。")
                continue
            wanted[f"{name}/{path}"] = (repo, commit, blob, path)
    if len(wanted) > limit:
        raise CommandError(f"一次复制了 {len(wanted)} 个文件，上限 {limit}。只复制这个任务要用的文件。")
    entries = []
    for key, (repo, commit, blob, path) in sorted(wanted.items()):
        try:
            content = targets.read_blob(repo, blob, found.timeout)
        except targets.TargetError as error:
            raise CommandError(str(error)) from error
        destination = target / repo.name / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            writable(destination)
        destination.write_bytes(content)
        entries.append({
            "path": destination.relative_to(target.parent).as_posix(),
            "source": key,
            "purpose": purpose,
            "sha256": store.sha256_file(destination),
            "repo": repo.name,
            "blob": blob,
            "base_commit": commit,
        })
        files[key] = {"blob": blob, "base_commit": commit}
    return entries


def staged_target_files(
    root: Path, data: Dict[str, Any], target: Path, taken: List[Dict[str, str]], limit: int
) -> List[Dict[str, str]]:
    """The files `add-input --from-target` staged, put into the builder's package too (the ones already there are skipped).

    They are read again by blob hash, so they are exactly what was staged, whatever main did since.
    """
    staged = [item for item in data["inputs"] if item.get("repo") and item.get("blob")]
    have = {item["source"] for item in taken}
    staged = [item for item in staged if item["source"] not in have]
    if not staged:
        return []
    if len(staged) > limit:
        raise CommandError(f"输入包会有 {len(taken) + len(staged)} 个文件，上限 {len(taken) + limit}。只复制这个任务要用的文件。")
    found = load_targets(root)
    entries = []
    for item in staged:
        repo = target_repo(found, item["repo"])
        try:
            content = targets.read_blob(repo, item["blob"], found.timeout)
        except targets.TargetError as error:
            raise CommandError(str(error)) from error
        destination = target / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            writable(destination)
        destination.write_bytes(content)
        entries.append({
            "path": destination.relative_to(target.parent).as_posix(), "source": item["source"], "purpose": "input",
            "sha256": store.sha256_file(destination), "repo": item["repo"], "blob": item["blob"], "base_commit": item["base_commit"],
        })
    return entries


def baseline_files(root: Path, data: Dict[str, Any], directory: Path, number: int, target: Path) -> List[Dict[str, str]]:
    """Reviewer: the main version of each file the builder changed or deletes, so a diff needs no look into the target repository."""
    handoff = store_json(layout.handoff_file(directory, number, "builder"))
    wanted = [(name, data.get("target_files", {}).get(name), "base") for name in handoff["outputs"]]
    wanted += [(name, data.get("target_files", {}).get(name), "deleted") for name in handoff.get("deletes", [])]
    wanted = [(name, record, purpose) for name, record, purpose in wanted if record]
    if not wanted:
        return []
    found = load_targets(root)
    entries = []
    for name, record, purpose in wanted:
        repo = target_repo(found, name.split("/", 1)[0])
        try:
            content = targets.read_blob(repo, record["blob"], found.timeout)
        except targets.TargetError as error:
            raise CommandError(str(error)) from error
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        entries.append({
            "path": destination.relative_to(target.parent).as_posix(), "source": name, "purpose": purpose,
            "sha256": store.sha256_file(destination), "repo": repo.name, "blob": record["blob"], "base_commit": record["base_commit"],
        })
    return entries


def add_input(root: Path, request_id: str, sources: List[str], from_target: Optional[List[str]] = None) -> Dict[str, Any]:
    if not sources and not from_target:
        raise CommandError("要给文件路径，或用 --from-target <仓库名>/<路径>。")
    rules = policy(root)
    directory = layout.request_dir(root, request_id)
    with store.locked(root, request_id) as data:
        store.require_open(data)
        if any_dispatched(data):
            raise CommandError("已经派发过输入包，init-inputs 不再改。要补充内容，放进下一轮：dispatch 时用 --input。")
        limit = rules["inputs"]["max_files"]
        entries = copy_in(root, sources, layout.init_inputs(directory), limit, "input")
        entries += copy_from_target(root, data, from_target or [], layout.init_inputs(directory), limit - len(entries), "input")
        known = {item["path"]: item for item in data["inputs"]}
        for entry in entries:
            name = entry["path"].split("/", 1)[1]  # relative to init-inputs/
            known[name] = {"path": name, "source": entry["source"], "sha256": entry["sha256"]}
            for extra in ("repo", "blob", "base_commit"):
                if extra in entry:
                    known[name][extra] = entry[extra]
        data["inputs"] = list(known.values())
    return {"added": [item["path"] for item in known.values() if item["source"] in {e["source"] for e in entries}], "total_inputs": len(data["inputs"])}


def set_brief(root: Path, request_id: str, source: str) -> Dict[str, Any]:
    rules = policy(root)
    directory = layout.request_dir(root, request_id)
    path = Path(source)
    path = path if path.is_absolute() else root / path
    if layout.inside(root, path) is None or not path.is_file():
        raise CommandError(f"`{source}` 不是仓库里的文件。把写好的 brief 放在请求目录里（例如 orchestrator/brief-draft.md）再提交。")
    text = path.read_text(encoding="utf-8")
    entries = brief_module.parse(text, rules)
    with store.locked(root, request_id) as data:
        store.require_open(data)
        digest = store.sha256_text(text)
        if data["brief"]["version"] and data["brief"]["sha256"] == digest:
            return {"brief_version": data["brief"]["version"], "entries": len(entries), "changed": False}
        version = data["brief"]["version"] + 1
        write_text(layout.brief_snapshot(directory, version), text)
        write_text(layout.brief_file(directory), text)
        data["brief"] = {"version": version, "sha256": digest, "entries": len(entries)}
    return {"brief_version": version, "entries": len(entries), "changed": True}


# --- attempts, dispatch ----------------------------------------------------------------------------------


def candidate_diff(package: Path, files: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Reviewer, request with target repositories: `candidate.diff`, what the builder changed against main.

    The reviewer reads this first instead of every candidate file and its main version side by side, which is most of the
    reviewer's input. Only the changed lines are shown, each with a few lines around it. Returns the manifest entry, or None
    when there is no base to compare with (a request without target repositories).
    """
    bases = {item["path"][len("base/"):]: item for item in files if item["purpose"] == "base"}
    deleted = [item for item in files if item["purpose"] == "deleted"]
    if not any(item["purpose"] == "candidate" for item in files) and not deleted:
        return None
    out = [
        "# 候选成果和 main 的差异。先读这个文件：只列出改动的行，每处带 3 行上下文。",
        "# 需要完整内容（运行、看更多上下文）时，读 candidate/<路径>；改动前的版本在 base/<路径>。",
    ]
    for item in files:
        if item["purpose"] != "candidate":
            continue
        name = item["path"][len("candidate/"):]
        new_bytes = (package / item["path"]).read_bytes()
        out.append(f"diff --git a/{name} b/{name}")
        if name not in bases:
            out.append("--- /dev/null")
            out.append(f"+++ b/{name}")
            try:
                out += ["+" + line for line in new_bytes.decode("utf-8").splitlines()]
            except UnicodeDecodeError:
                out.append("（二进制文件，不显示内容）")
            continue
        old_bytes = (package / bases[name]["path"]).read_bytes()
        if old_bytes == new_bytes:
            out.append("（和 main 上的版本一样，没有改动）")
            continue
        try:
            out += list(difflib.unified_diff(old_bytes.decode("utf-8").splitlines(), new_bytes.decode("utf-8").splitlines(), f"a/{name}", f"b/{name}", lineterm="", n=3))
        except UnicodeDecodeError:
            out.append("（二进制文件，不显示差异）")
    for item in deleted:
        name = item["path"][len("base/"):]
        out += [f"diff --git a/{name} b/{name}", "deleted file", f"--- a/{name}", "+++ /dev/null"]
        try:
            out += ["-" + line for line in (package / item["path"]).read_bytes().decode("utf-8").splitlines()]
        except UnicodeDecodeError:
            out.append("（二进制文件，不显示内容）")
    destination = package / "candidate.diff"
    destination.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"path": "candidate.diff", "source": "（由 dispatch 生成）", "purpose": "diff", "sha256": store.sha256_file(destination)}


def fill_reviewer_assignment(directory: Path, number: int) -> bool:
    """The reviewer's goal and acceptance criteria default to the builder's: the same text written twice only costs output.

    Fills only the sections still "（待填）". Returns whether anything was copied.
    """
    reviewer = layout.package_dir(directory, number, "reviewer") / "assignment.md"
    builder = layout.package_dir(directory, number, "builder") / "assignment.md"
    if not reviewer.is_file() or not builder.is_file():
        return False
    text, source = reviewer.read_text(encoding="utf-8"), builder.read_text(encoding="utf-8")
    changed = False
    for heading in ("## 目标", "## 验收标准"):
        have, mine = section_body(source, heading), section_body(text, heading)
        if mine == PLACEHOLDER and have and have != PLACEHOLDER:
            text = text.replace(f"{heading}\n\n{PLACEHOLDER}", f"{heading}\n\n{have}", 1)
            changed = True
    if changed:
        write_text(reviewer, text)
    return changed


def section_body(text: str, heading: str) -> str:
    parts = text.split(heading, 1)
    return parts[1].split("\n## ", 1)[0].strip() if len(parts) == 2 else ""


def assignment_text(root: Path, request_id: str, number: int, role: str, directory: Path, note: str = "") -> str:
    template = (root / ".harness" / "contracts" / "templates" / "assignment.md").read_text(encoding="utf-8")
    outputs = layout.inside(root, layout.outputs_dir(directory, number, role)) or ""
    return (
        template.replace("{role}", role)
        .replace("{attempt}", str(number))
        .replace("{request_id}", request_id)
        .replace("{outputs_dir}", outputs)
        .replace("{cli}", cli_command())
        .replace("{mkdir}", mkdir_command())
        .replace("{target_note}\n", note + "\n" if note else "")
    )


def new_attempt(root: Path, request_id: str, human_approved: str = "") -> Dict[str, Any]:
    rules = policy(root)
    directory = layout.request_dir(root, request_id)
    approved = human_approved.strip()
    with store.locked(root, request_id) as data:
        store.require_open(data)
        number = data["attempt"] + 1
        if number > rules["max_attempts"] and not approved:
            raise CommandError(
                f"已经做了 {data['attempt']} 轮，到了上限（{rules['max_attempts']} 轮）。"
                "先在对话里问用户要不要继续。用户同意后，用 --human-approved \"<原因>\" 重试。"
                "不同意，或要改需求，就 `request set-status hitl --reason ...`。不要自己重置计数。"
            )
        if number > 1 and not data["attempts"][-1]["handoffs"]:
            raise CommandError(f"第 {number - 1} 轮还没有任何 handoff，不能开下一轮。先让它交接（handoff submit），或 `request set-status abandoned`。")
        from . import planapproval  # it imports this module

        planapproval.require_approved(root, request_id, data)
        found = load_targets(root) if data.get("target_mode") else None
        for role in layout.ROLES:
            note = target_note(data, found, role) if found else ""
            package = layout.package_dir(directory, number, role)
            (package / ("candidate" if role == "reviewer" else "inputs")).mkdir(parents=True, exist_ok=True)
            write_text(package / "assignment.md", assignment_text(root, request_id, number, role, directory, note))
            layout.outputs_dir(directory, number, role).mkdir(parents=True, exist_ok=True)
            layout.handoff_file(directory, number, role).parent.mkdir(parents=True, exist_ok=True)
        data["attempt"] = number
        data["attempts"].append(
            {"n": number, "created_at": utc_now(), "human_approved": approved if number > rules["max_attempts"] else "", "dispatched": {}, "handoffs": {}}
        )
    base = layout.REQUESTS_DIR + "/" + request_id + "/handoffs/orchestrator/" + layout.attempt_name(number)
    return {
        "attempt": number,
        "assignments": [f"{base}/to-{role}/assignment.md" for role in layout.ROLES],
        "next": "填好 to-builder/assignment.md（目标和验收标准，去掉“（待填）”），再 dispatch --role builder。reviewer 的任务书不用填：dispatch reviewer 时会抄 builder 的目标和验收标准（要不同的才自己填）。",
    }


def check_assignment(path: Path, role: str) -> None:
    text = path.read_text(encoding="utf-8")
    if PLACEHOLDER in text:
        raise CommandError(f"to-{role}/assignment.md 里还有“{PLACEHOLDER}”。填好目标和验收标准再派发。")
    section = text.split("## 验收标准", 1)
    body = section[1].split("\n## ", 1)[0].strip() if len(section) == 2 else ""
    if not body:
        raise CommandError("assignment.md 缺“## 验收标准”或里面是空的。验收标准必填。")


def previous_files(root: Path, directory: Path, number: int, target: Path) -> List[Dict[str, str]]:
    """Attempt 2 and later, builder: the handoffs of the last attempt and the evidence they list, copied in."""
    entries = []
    previous = number - 1
    for role in layout.ROLES:
        handoff = layout.handoff_file(directory, previous, role)
        if not handoff.exists():
            continue
        found = store_json(handoff)
        names = [(handoff, f"{role}-handoff.json")]
        base = layout.outputs_dir(directory, previous, role)
        names += [(base / item, f"{role}-evidence/{item}") for item in found.get("evidence", []) if (base / item).is_file()]
        for source, name in names:
            destination = target / "previous-attempt" / name
            copy_file(source, destination)
            entries.append(entry(root, source, destination, target.parent, "previous-attempt"))
    return entries


def store_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def candidate_files(root: Path, directory: Path, number: int, target: Path) -> List[Dict[str, str]]:
    handoff = store_json(layout.handoff_file(directory, number, "builder"))
    base = layout.outputs_dir(directory, number, "builder")
    entries = []
    for item in handoff["outputs"]:
        source = base / layout.relative_name(item, "成果路径")
        if not source.is_file():
            raise CommandError(f"builder 的 handoff 列出了 `{item}`，但 {layout.inside(root, source)} 不存在。让 builder 补上再交接。")
        destination = target / layout.relative_name(item, "成果路径")
        copy_file(source, destination)
        entries.append(entry(root, source, destination, target.parent, "candidate"))
    return entries


def last_brief_version(data: Dict[str, Any], role: str, number: int) -> int:
    """The brief version this role was last dispatched with, before attempt `number`. 0 when it has none."""
    for attempt in reversed(data["attempts"][: number - 1]):
        if role in attempt["dispatched"]:
            return attempt["dispatched"][role]["brief_version"]
    return 0


def dispatch(root: Path, request_id: str, role: str, inputs: Optional[List[str]] = None, from_target: Optional[List[str]] = None) -> Dict[str, Any]:
    if role not in layout.ROLES:
        raise CommandError("--role 只能是 builder 或 reviewer。")
    rules = policy(root)
    directory = layout.request_dir(root, request_id)
    with store.locked(root, request_id) as data:
        store.require_open(data)
        number = data["attempt"]
        if number < 1:
            raise CommandError("还没有 attempt。先 `attempt new`。")
        attempt = data["attempts"][number - 1]
        if role in attempt["dispatched"]:
            raise CommandError(f"第 {number} 轮的 {role} 已经派发过，输入包不能再改，也不能派发第二次。需要补充内容，用 `attempt new` 开下一轮。")
        if role == "reviewer":
            status = attempt["handoffs"].get("builder")
            if status is None:
                raise CommandError("builder 这一轮还没有 handoff，不能派发 reviewer。先让 builder 交接。")
            if status != "passed":
                raise CommandError(f"builder 这一轮的 handoff 是 {status}，没有成果可评审。用 `attempt new` 开下一轮让它返工，或 `request set-status hitl`。")
        package = layout.package_dir(directory, number, role)
        assignment = package / "assignment.md"
        copied = fill_reviewer_assignment(directory, number) if role == "reviewer" else False
        check_assignment(assignment, role)
        files: List[Dict[str, str]] = []
        try:
            files += copy_in(root, inputs or [], package / "inputs", rules["inputs"]["max_files"], "input")
            files += copy_from_target(root, data, from_target or [], package / "inputs", rules["inputs"]["max_files"] - len(files), "input")
            if role == "builder":
                files += staged_target_files(root, data, package / "inputs", files, rules["inputs"]["max_files"] - len(files))
            if role == "builder" and number > 1:
                files += previous_files(root, directory, number, package / "inputs")
            if role == "reviewer":
                files += candidate_files(root, directory, number, package / "candidate")
                files += baseline_files(root, data, directory, number, package / "base")
                diff = candidate_diff(package, files) if data.get("target_mode") else None
                if diff:
                    files.append(diff)
            brief_path = layout.brief_file(directory)
            version = data["brief"]["version"]
            delta: List[str] = []
            earlier = last_brief_version(data, role, number)
            if version and earlier and earlier != version:
                delta = brief_module.delta(layout.brief_snapshot(directory, earlier).read_text(encoding="utf-8"), brief_path.read_text(encoding="utf-8"))
            manifest = {
                "schema_version": store.SCHEMA_VERSION,
                "request_id": request_id,
                "attempt": number,
                "role": role,
                "assignment": {"path": assignment.relative_to(package).as_posix(), "sha256": store.sha256_file(assignment)},
                "files": files,
                "brief": layout.inside(root, brief_path) if version else None,
                "brief_version": version,
                "brief_delta": delta,
                "dispatched_at": utc_now(),
            }
            store.validate(root, "manifest", manifest, "manifest.json")
            write_text(package / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        except BaseException:
            (package / "manifest.json").unlink() if (package / "manifest.json").exists() else None
            for sub in ("inputs", "candidate", "base"):
                shutil.rmtree(str(package / sub), ignore_errors=True)
                if sub != "base":
                    (package / sub).mkdir(parents=True, exist_ok=True)
            raise
        for file in [assignment, package / "manifest.json"] + [package / item["path"] for item in files]:
            read_only(file)
        attempt["dispatched"][role] = {"at": manifest["dispatched_at"], "brief_version": version}
        data["pending_dispatch"].append({"role": role, "attempt": number, "at": manifest["dispatched_at"]})
    return {
        "role": role,
        "attempt": number,
        "package": layout.inside(root, package),
        "files": len(files),
        "brief_version": version,
        "brief_delta": len(delta),
        **({"assignment_copied_from_builder": True} if copied else {}),
        "next": f"调用 {role} 子 agent，让它先读 {layout.inside(root, assignment)}。",
    }


# --- handoff ------------------------------------------------------------------------------------------------


def check_target_output(found: targets.Targets, name: str, label: str = "--output") -> None:
    """In a request with target repositories every result path is `<repo>/<path in the repo>`, and not a path promote refuses."""
    repo_name, _, rest = name.partition("/")
    if repo_name not in found.repos or not rest:
        known = "、".join(found.names()) or "（没有）"
        raise CommandError(f"{label} `{name}` 的第一段要是仓库名，后面是仓库里的路径，例如 bdtt_repo/src/a.sql。已知的仓库：{known}。")
    for pattern in found.repos[repo_name].refused_paths:
        if repo_paths.glob_regex(pattern).match(rest):
            raise CommandError(f"{label} `{name}` 属于不能回写的路径（{repo_name} 的 {pattern}）。把它从成果里去掉。")


def parse_kb(items: List[str]) -> List[Dict[str, str]]:
    found = []
    for item in items:
        source, separator, note = item.partition("::")
        if not separator or not source.strip() or not note.strip():
            raise CommandError(f"--kb-addition `{item}` 格式不对。写成 `来源 :: 一句话结论`，例如 `knowledge-base/a.md#部署 :: 先停写再迁移`。")
        found.append({"source": source.strip(), "note": note.strip()})
    return found


def submit_handoff(
    root: Path,
    request_id: str,
    role: str,
    status: str,
    summary: str,
    outputs: Optional[List[str]] = None,
    deletes: Optional[List[str]] = None,
    evidence: Optional[List[str]] = None,
    blockers: Optional[List[str]] = None,
    next_step: str = "",
    kb_additions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if role not in layout.ROLES:
        raise CommandError("--role 只能是 builder 或 reviewer。")
    if status not in ("passed", "failed", "blocked"):
        raise CommandError("--status 只能是 passed、failed 或 blocked。")
    rules = policy(root)
    directory = layout.request_dir(root, request_id)
    outputs, evidence, blockers = outputs or [], evidence or [], [item.strip() for item in (blockers or []) if item.strip()]
    deletes = deletes or []
    if deletes and role != "builder":
        raise CommandError("--delete 只有 builder 能用。reviewer 只评审，不改成果。")
    lines = [line for line in summary.splitlines() if line.strip()]
    if not lines:
        raise CommandError("--summary 不能为空。")
    if len(lines) > rules["handoff"]["summary_max_lines"]:
        raise CommandError(f"summary 有 {len(lines)} 行，上限 {rules['handoff']['summary_max_lines']} 行。细节放进成果和证据文件，handoff 只做索引。")
    with store.locked(root, request_id) as data:
        store.require_open(data)
        number = data["attempt"]
        if number < 1 or role not in data["attempts"][number - 1]["dispatched"]:
            raise CommandError(f"第 {number} 轮的 {role} 还没有被派发，不能交接。由 orchestrator 先 `dispatch --role {role}`。")
        target = layout.handoff_file(directory, number, role)
        if target.exists():
            raise CommandError(f"第 {number} 轮的 {role} 已经交接过（{data['attempts'][number - 1]['handoffs'].get(role)}），handoff 不能覆盖。")
        if status in ("failed", "blocked") and not blockers:
            raise CommandError(f"status 是 {status} 时，要用 --blocker 写明原因（缺什么、哪里没通过）。")
        if status == "passed" and role == "builder" and not outputs and not deletes:
            raise CommandError("builder 的 status 是 passed 时，要用 --output 列出成果文件（只删文件时用 --delete）。")
        if status == "passed" and role == "reviewer" and not evidence:
            raise CommandError("reviewer 的 status 是 passed 时，要用 --evidence 列出证据文件。")
        base = layout.outputs_dir(directory, number, role)
        clean_outputs, clean_evidence = [], []
        found = load_targets(root) if data.get("target_mode") else None
        for items, clean, label in ((outputs, clean_outputs, "--output"), (evidence, clean_evidence, "--evidence")):
            for item in items:
                name = layout.relative_name(item, label)
                if found is not None and label == "--output":
                    check_target_output(found, name)
                if not (base / name).is_file():
                    raise CommandError(f"{label} `{item}` 不是文件：{layout.inside(root, base / name)}。成果和证据放在 {layout.inside(root, base)}/ 下，路径相对于它。")
                clean.append(name)
        clean_deletes: List[str] = []
        if deletes:
            if found is None:
                raise CommandError("--delete 只用在有目标仓库的请求里。没配置目标仓库时，回写不能删文件。")
            for item in deletes:
                name = layout.relative_name(item, "--delete")
                check_target_output(found, name, "--delete")
                if name not in data.get("target_files", {}):
                    raise CommandError(f"--delete `{name}` 不是这个请求从 main 取过的文件。要删的文件要先 `request add-input --request {request_id} --from-target {name}`，在 dispatch builder 之前。")
                if name in clean_outputs:
                    raise CommandError(f"`{name}` 同时出现在 --output 和 --delete 里。")
                if name not in clean_deletes:
                    clean_deletes.append(name)
        handoff = {
            "schema_version": store.SCHEMA_VERSION,
            "request_id": request_id,
            "attempt": number,
            "role": role,
            "status": status,
            "summary": "\n".join(lines),
            "outputs": clean_outputs,
            **({"deletes": clean_deletes} if clean_deletes else {}),
            "evidence": clean_evidence,
            "blockers": blockers,
            "next": next_step.strip(),
            "kb_additions": parse_kb(kb_additions or []),
            "submitted_at": utc_now(),
        }
        store.validate(root, "handoff", handoff, "handoff.json")
        write_text(target, json.dumps(handoff, indent=2, ensure_ascii=False) + "\n")
        read_only(target)
        data["attempts"][number - 1]["handoffs"][role] = status
    return {"role": role, "attempt": number, "status": status, "handoff": layout.inside(root, target), "kb_additions": len(handoff["kb_additions"])}


# --- set-status --------------------------------------------------------------------------------------


def wait(root: Path, request_id: str, reason: str) -> Dict[str, Any]:
    """Mark the request as waiting for a person, so the Stop check lets the agent end its turn. Cleared by the next user prompt."""
    reason = reason.strip()
    if not reason:
        raise CommandError("--reason 要写明在等什么（例如：等用户批准 promote）。")
    from . import verify

    with store.locked(root, request_id) as data:
        store.require_open(data)
        verify.mark_waiting(data, reason)
    return {
        "request_id": request_id,
        "waiting_for": reason,
        "next": "现在可以把问题交给用户，并结束这一轮。用户的下一条提示到达时，等待标记自动清除。",
    }


def _has_candidates(root: Path, request_id: str, data: Dict[str, Any]) -> bool:
    """Did the last reviewer package hold result files, i.e. something promote would write?"""
    path = layout.package_dir(layout.request_dir(root, request_id), data["attempt"], "reviewer") / "manifest.json"
    if not path.is_file():
        return False
    return any(item.get("purpose") in ("candidate", "deleted") for item in store_json(path).get("files", []))


def set_status(root: Path, request_id: str, status: str, reason: str = "") -> Dict[str, Any]:
    if status not in STATUS_ENDS:
        raise CommandError("--status 只能是 accepted、hitl 或 abandoned。")
    reason = reason.strip()
    with store.locked(root, request_id) as data:
        store.require_open(data)
        if status in ("hitl", "abandoned") and not reason:
            raise CommandError(f"设成 {status} 要用 --reason 写明原因。")
        if status == "accepted":
            last = data["attempts"][-1] if data["attempts"] else None
            if not (last and last["handoffs"].get("reviewer") == "passed") and not reason:
                raise CommandError("最后一轮 reviewer 还不是 passed，不能 accepted。要么先走完评审，要么用 --reason 写明为什么可以跳过评审。")
            if last and last["handoffs"].get("reviewer") == "passed" and data["promote"]["state"] != "done" and _has_candidates(root, request_id, data):
                if not reason:
                    raise CommandError(
                        "reviewer 评审过的成果还没有 promote，不能 accepted（结束后就不能再 promote）。"
                        "先 `promote --dry-run`，`request wait` 等用户批准，再 `promote`。成果确实不需要回写，才用 --reason 写明理由。"
                    )
        data["status"] = status
        data["status_reason"] = reason
        data.pop("waiting", None)
        surface, session_id = data.get("surface", "vscode"), data["session_id"]
    released = False
    if state_path(root, surface, session_id).exists():
        with session(root, surface, session_id) as state:
            if state["active_request"] == request_id:
                state["active_request"] = None
                released = True
    result = {"request_id": request_id, "status": status, "session_released": released, "next": "会话回到 L1。" if released else ""}
    try:
        from . import report  # a report needs this module, so it is imported here

        result["report"] = report.generate(root, request_id)["report"]
    except Exception as error:  # the conclusion is already written; a missing report must not undo it
        result["report_error"] = f"{type(error).__name__}: {error}"
    return result
