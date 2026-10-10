"""The L2 task (M7): one agent, a task folder, and the same two approvals as an L3 request.

  task start          the session enters task mode for `.workspace/current_tasks/<task>`; DEV/ and the state are made
  task approve-plan   the person approves PLAN.md (terminal only); until then the gate keeps DEV/ closed. Results that
                      do not go back to a repository (an RCA, a design) are written at the top of the task folder and need no plan
  task fetch          a file of a target repository as its base branch has it, copied to DEV/<repo>/<path>; the same
                      bytes are kept under .task/base/ so a diff needs no look into the repository
  task delete         a fetched file is to be deleted in the repository
  task diff           what DEV/ changes against the fetched versions, written to CHANGES.diff
  task promote        like the L3 promote: checked for every repository, approved by the person, written to a new branch.
                      A file directly in DEV/ (not under a repository name) is not written back; the plan lists it
  task close          the session leaves task mode; the report is written

There is no sandbox, no handoff and no second agent. The state is `<task>/.task/task.json`; only this file writes it.
The plan and promote checks are the ones of the L3 request (`promote_target`, `core/approval`).
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from core import approval, tasks
from core.paths import cli_command, utc_now
from core.state import admin_on, atomic_write, session, state_lock, state_path

from . import layout, ops, promote, promote_target, store
from .layout import CommandError

SCHEMA_VERSION = 1
EVENTS_KEPT = 200
SKIP_TOP = ("_deleted",)
VERIFY_TEXT = {"on": "开启（用户写了开启标记）", "off": "关闭（用户写了跳过标记）"}
HINTS = {
    "fetch": "先 `task fetch {key}` 取过再改。",
    "refetch": "把你的改动另存，`task fetch --overwrite` 重新取文件，再改一遍。",
    "set_branch": "用 `task set-branch --branch feature/<名字>` 设一个。",
    "rename_branch": "换一个分支名（`task set-branch`），或先处理掉那个分支。",
    "drop": "把它从 DEV/ 里拿掉。",
    "stray": "要回写：放到 DEV/<仓库名>/<路径> 下。不回写：用终端命令把它移到任务目录根下（DEV/ 之外），再重新 --dry-run。",
}


# --- state ---------------------------------------------------------------------------------------


def name_of(task: str) -> str:
    return task.rstrip("/").rsplit("/", 1)[-1]


def default_branch(task: str, number: int) -> str:
    text = re.sub(r"[^A-Za-z0-9_]", "_", name_of(task))[:50] or "task"
    return f"feature/{text}" + (f"_r{number}" if number > 1 else "")


def read(root: Path, task: str) -> Dict[str, Any]:
    data = tasks.read(root, task)
    if data is None:
        raise CommandError(f"任务 `{task}` 还没有开始。先运行 `{cli_command()} task start --task {task} --session-id <会话 id>`。")
    return data


@contextmanager
def locked(root: Path, task: str) -> Iterator[Dict[str, Any]]:
    """Lock task.json, yield its data, write it back if the block ends without an exception."""
    path = tasks.state_file(root, task)
    if not path.exists():
        read(root, task)
    with state_lock(path):
        data = read(root, task)
        yield data
        data["updated_at"] = utc_now()
        atomic_write(path, data)


def note(data: Dict[str, Any], what: str, detail: str = "") -> None:
    """One line of the audit trail the report prints."""
    data.setdefault("events", []).append({"at": utc_now(), "round": data["round"], "what": what, "detail": detail})
    del data["events"][:-EVENTS_KEPT]


def require_open(data: Dict[str, Any]) -> None:
    if data["status"] != "open":
        raise CommandError(f"任务已经关闭。要接着做，重新运行 `{cli_command()} task start --task {data['task']} --session-id <会话 id>`。")


def open_tasks(root: Path) -> List[Dict[str, Any]]:
    found = []
    base = root / tasks.TASKS_DIR
    for path in sorted(base.iterdir()) if base.is_dir() else []:
        data = tasks.read(root, f"{tasks.TASKS_DIR}/{path.name}")
        if data and data.get("status") == "open":
            found.append(data)
    return found


def resolve(root: Path, raw: str, waiting: Optional[Callable[[Dict[str, Any]], bool]] = None, what: str = "") -> str:
    """The task a command means. `raw` may be the folder path or just its name. Left out: the one open task (that `waiting` picks)."""
    text = raw.strip()
    if text:
        if "/" not in text.replace("\\", "/").strip("/"):
            text = f"{tasks.TASKS_DIR}/{text}"
        return ops.clean_task(root, text)
    found = [item for item in open_tasks(root) if waiting is None or waiting(item)]
    if not found:
        raise CommandError(f"没有{what or '进行中的'}任务。用 --task 指定任务目录。")
    if len(found) > 1:
        raise CommandError(f"有好几个{what or '进行中的'}任务：" + "、".join(item["task"] for item in found) + "。用 --task 指定一个。")
    return found[0]["task"]


def rel(root: Path, path: Path) -> str:
    return layout.inside(root, path) or str(path)


# --- start, status, close ------------------------------------------------------------------------


def start(root: Path, raw_task: str, session_id: str, surface: str = "vscode", branch: str = "") -> Dict[str, Any]:
    task = resolve(root, raw_task) if raw_task.strip() else ""
    if not task:
        raise CommandError("--task 要是 .workspace/current_tasks/ 下的一个任务目录。")
    found = ops.load_targets(root)
    branch_name = ops.clean_branch(branch)
    if not state_path(root, surface, session_id).exists():
        raise CommandError(f"没有会话 `{session_id}`。用本条提示开头规则里写的“当前会话 id”，原样抄，不要改。")
    path = tasks.state_file(root, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    with session(root, surface, session_id) as state:
        if state.get("active_request"):
            raise CommandError(f"这个会话有进行中的 L3 请求 `{state['active_request']}`。任务模式是 L2 的，先结束那个请求。")
        if state.get("parent_session_id"):
            raise CommandError("子 agent 不能开任务。")
        if admin_on(state):
            raise CommandError("这个会话在 admin 模式里，不能开任务。admin 只用来二开和排查 harness；做任务请用户换一个对话，或先运行 `admin off`。")
        if state["level"] != 2:
            raise CommandError("任务模式只在 L2 用。停下来，请用户在提示开头写 /l2 重发。L1 不改目标仓库，也不开任务。")
        other = state.get("active_task")
        if other and other != task and (tasks.read(root, other) or {}).get("status") == "open":
            raise CommandError(f"这个会话已经在做任务 `{other}`。先 `task close --task {other}`，再开新的。")
        with state_lock(path):
            data = tasks.read(root, task)
            resumed, new_round = data is not None, False
            if data is None:
                now = utc_now()
                data = {
                    "schema_version": SCHEMA_VERSION, "task": task, "name": name_of(task), "session_id": session_id, "surface": surface,
                    "status": "open", "created_at": now, "updated_at": now, "round": 1, "round_started_at": now,
                    "target_mode": found.configured, "branch": "", "targets": {}, "target_files": {}, "deletes": [],
                    "plan": {}, "promote": {"state": "none"}, "rounds": [], "events": [], "verify": "",
                }
                note(data, "start", f"会话 {session_id}")
            else:
                state_now = data["promote"]["state"]
                if state_now == "partial":
                    raise CommandError(f"这个任务上次的 promote 中途出错。先请用户在自己的终端运行 `{cli_command()} task recover --task {task}`。")
                if state_now == "done":
                    new_round = True
                    archive_round(root, task, data)
                data.update(status="open", session_id=session_id, surface=surface, target_mode=found.configured)
                note(data, "new-round" if new_round else "resume", f"会话 {session_id}")
            marker = ((state["modules"].get("task_level") or {}).get("prompt") or {}).get("verify", "")
            if marker in ("on", "off") and marker != tasks.verify_choice(data):
                # The user wrote [verify] or [no-verify] in the prompt that starts the task: it holds for the whole task.
                data["verify"] = marker
                note(data, "verify", VERIFY_TEXT[marker])
            if branch_name:
                data["branch"] = branch_name
            elif found.configured and not data["branch"]:
                data["branch"] = default_branch(task, data["round"])
            tasks.dev_dir(root, task).mkdir(parents=True, exist_ok=True)
            data["updated_at"] = utc_now()
            atomic_write(path, data)
        state["active_task"] = task
    approved = tasks.plan_approved(root, task, data)
    result: Dict[str, Any] = {
        "task": task, "round": data["round"], "resumed": resumed and not new_round, "new_round": new_round,
        "plan": f"{task}/{tasks.PLAN_NAME}", "plan_approved": approved, "dev": f"{task}/{tasks.DEV_NAME}",
        "next": next_step(root, task, data), "verify": tasks.verify_choice(data),
    }
    if found.configured:
        result.update(branch=data["branch"], target_repos=found.names())
    return result


def set_verify(root: Path, task: str, choice: str) -> Dict[str, Any]:
    """Called by the hook when the user writes a verifier marker in a later prompt of the task. Returns the new state."""
    with locked(root, task) as data:
        data["verify"] = choice
        note(data, "verify", VERIFY_TEXT[choice])
    return data


def archive_round(root: Path, task: str, data: Dict[str, Any]) -> None:
    """A promoted task that is started again begins a new round: the old result moves aside, the plan needs a new approval."""
    number = data["round"]
    dev = tasks.dev_dir(root, task)
    kept = dev.parent / f"{tasks.DEV_NAME}_r{number}"
    if dev.is_dir() and any(dev.iterdir()) and not kept.exists():
        dev.rename(kept)
    shutil.rmtree(str(tasks.base_dir(root, task)), ignore_errors=True)
    plan = tasks.plan_file(root, task)
    old_plan = plan.with_name(f"{plan.stem}_r{number}{plan.suffix}")
    if plan.is_file() and not old_plan.exists():
        plan.rename(old_plan)  # the new round starts without a plan, so the old one cannot be approved again by mistake
    data["rounds"].append({
        "round": number, "started_at": data.get("round_started_at", ""), "plan": data.get("plan", {}), "promote": data["promote"],
        "branch": data["branch"], "dev": rel(root, kept), "plan_file": rel(root, old_plan) if old_plan.exists() else "", "files": sorted(data["target_files"]), "deletes": list(data["deletes"]),
    })
    data.update(round=number + 1, round_started_at=utc_now(), targets={}, target_files={}, deletes=[], plan={}, promote={"state": "none"}, branch="")


def next_step(root: Path, task: str, data: Dict[str, Any]) -> str:
    plan = f"{task}/{tasks.PLAN_NAME}"
    if not tasks.plan_digest(root, task):
        return (
            f"读 REQ/、REF/ 和知识库。要改目标仓库：把计划写到 {plan}（要改哪些文件、怎么改、怎么验收），写完就停，给用户 [PLAN.md]({plan}) 的链接，"
            f"请用户在自己的终端运行 `{cli_command()} task approve-plan`；批准前不能写 {task}/{tasks.DEV_NAME}/。"
            f"不改目标仓库的成果（RCA、设计、笔记）不需要计划，直接写在 {task}/ 根下。"
        )
    if not tasks.plan_approved(root, task, data):
        return (
            f"计划还没有经用户批准（或批准之后改过）。给用户 [PLAN.md]({plan}) 的链接，请用户在自己的终端运行 `{cli_command()} task approve-plan`。"
            f"批准前不能写 {task}/{tasks.DEV_NAME}/；不回写的成果可以先写在 {task}/ 根下。"
        )
    text = f"计划已批准。要回写到目标仓库的成果写在 {task}/{tasks.DEV_NAME}/<仓库名>/<路径> 下；不回写的成果（RCA、设计、一次性脚本）写在 {task}/ 根下。"
    if data.get("target_mode"):
        text += "要改仓库里已有的文件，先用 `task fetch <仓库名>/<路径>` 取进来；做完 `task diff`，再 `task promote --dry-run`。"
    return text + "全部做完后 `task close`。"


def status(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = resolve(root, raw_task)
    data = read(root, task)
    return {
        "task": task, "status": data["status"], "round": data["round"], "branch": data.get("branch", ""),
        "plan_written": bool(tasks.plan_digest(root, task)), "plan_approved": tasks.plan_approved(root, task, data),
        "fetched": sorted(data["target_files"]), "deletes": data["deletes"], "promote": data["promote"]["state"],
        "verify": tasks.verify_choice(data),
        "next": next_step(root, task, data) if data["status"] == "open" else "",
    }


def set_branch(root: Path, raw_task: str, branch: str) -> Dict[str, Any]:
    name = ops.clean_branch(branch)
    if not name:
        raise CommandError("--branch 不能为空。")
    task = resolve(root, raw_task)
    with locked(root, task) as data:
        require_open(data)
        if not data.get("target_mode"):
            raise CommandError("没有配置目标仓库，不需要分支名。")
        if data["promote"]["state"] in ("done", "partial"):
            raise CommandError("已经 promote 过（或中途出错），分支名不能再改。")
        reset = data["promote"]["state"] == "dry_run"
        if reset:
            data["promote"] = {"state": "none"}  # the plan names the branch: a new name needs a new dry-run and a new approval
        data["branch"] = name
        note(data, "set-branch", name)
    return {"task": task, "branch": name, "promote_plan_reset": reset}


def close(root: Path, raw_task: str = "", reason: str = "") -> Dict[str, Any]:
    task = resolve(root, raw_task)
    with locked(root, task) as data:
        if data["promote"]["state"] == "partial":
            raise CommandError(f"promote 中途出错，还没有恢复。先请用户在自己的终端运行 `{cli_command()} task recover --task {task}`。")
        data["status"] = "closed"
        note(data, "close", reason.strip())
        surface, session_id = data.get("surface", "vscode"), data["session_id"]
    released = False
    if state_path(root, surface, session_id).exists():
        with session(root, surface, session_id) as state:
            if state.get("active_task") == task:
                state["active_task"] = None
                released = True
    result: Dict[str, Any] = {"task": task, "status": "closed", "session_released": released}
    try:
        from . import task_report  # it needs this module

        result["report"] = task_report.generate(root, task)["report"]
    except Exception as error:  # the task is closed; a missing report must not undo that
        result["report_error"] = f"{type(error).__name__}: {error}"
    return result


# --- plan approval -------------------------------------------------------------------------------


def require_plan(root: Path, task: str, data: Dict[str, Any]) -> None:
    if not tasks.plan_approved(root, task, data):
        raise CommandError(next_step(root, task, data) + "用户说批准了，再运行这条命令。")


def person(command: str, interactive: Optional[bool]) -> None:
    try:
        approval.require_person(command, interactive)
    except approval.Refused as error:
        raise CommandError(str(error)) from error


def typed(question: str, digest: str, refusal: str, reader: Optional[Callable[[str], str]]) -> None:
    try:
        approval.ask(question, digest, refusal, reader)
    except approval.Refused as error:
        raise CommandError(str(error)) from error


def approve_plan(
    root: Path, raw_task: str = "", reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None,
) -> Dict[str, Any]:
    """The person approves PLAN.md as it is now. The screen names the file; the person reads it in the editor."""
    person("approve-plan", interactive)
    task = resolve(root, raw_task, lambda item: bool(tasks.plan_digest(root, item["task"])) and not tasks.plan_approved(root, item["task"], item), "等待批准计划的")
    data = read(root, task)
    require_open(data)
    current = tasks.plan_digest(root, task)
    plan = tasks.plan_file(root, task)
    if not current or not plan.read_text(encoding="utf-8", errors="replace").strip():
        raise CommandError(f"还没有计划文件 {task}/{tasks.PLAN_NAME}，或者它是空的。先让 agent 写好计划。")
    lines = len(plan.read_text(encoding="utf-8", errors="replace").splitlines())
    approval.say(
        out,
        f"任务 {task}（第 {data['round']} 轮）",
        f"计划在这个文件里（{lines} 行），先在编辑器里打开看：{task}/{tasks.PLAN_NAME}",
        f"批准后 agent 才能在 {task}/{tasks.DEV_NAME}/ 下写文件。计划再改，要重新批准。",
    )
    typed("确认按这份计划做", current, "没有批准。agent 还不能开工。", reader)
    with locked(root, task) as again:
        require_open(again)
        if tasks.plan_digest(root, task) != current:
            raise CommandError("你确认的时候计划变了。重新打开文件看一遍，再运行 approve-plan。")
        again["plan"] = {"approved_sha256": current, "approved_at": utc_now()}
        note(again, "approve-plan", current[:12])
    return {"approved": True, "task": task, "plan": f"{task}/{tasks.PLAN_NAME}", "next": "告诉 agent 计划已批准，可以开工了。"}


# --- fetch, delete, diff -------------------------------------------------------------------------


def fetch(root: Path, raw_task: str, specs: List[str], overwrite: bool = False) -> Dict[str, Any]:
    if not specs:
        raise CommandError("要写 `<仓库名>/<路径>`，例如 bdtt_repo/src/a.sql。")
    task = resolve(root, raw_task)
    limit = ops.policy(root)["inputs"]["max_files"]
    base, dev = tasks.base_dir(root, task), tasks.dev_dir(root, task)
    fetched: List[str] = []
    kept: List[str] = []
    with locked(root, task) as data:
        require_open(data)
        require_plan(root, task, data)
        if data["promote"]["state"] in ("done", "partial"):
            raise CommandError("这一轮已经 promote 过。要再改，重新 `task start` 开新的一轮。")
        found = ops.load_targets(root)
        for spec in specs:
            name, _, rest = spec.strip().replace("\\", "/").partition("/")
            if name in found.repos and rest.strip("/"):
                ops.check_target_output(found, f"{name}/{rest.strip('/')}", "fetch")
        entries = ops.copy_from_target(root, data, specs, base, limit, "base")
        for entry in entries:
            key = entry["source"]
            source, destination = base / key, dev / key
            if destination.exists() and not overwrite and store.sha256_file(destination) != entry["sha256"]:
                kept.append(key)  # the agent's edits stay; `--overwrite` takes the base version again
            else:
                ops.copy_file(source, destination)
                fetched.append(key)
            if key in data["deletes"]:
                data["deletes"].remove(key)
        if fetched or kept:
            data["promote"] = {"state": "none"} if data["promote"]["state"] == "dry_run" else data["promote"]
            note(data, "fetch", "、".join(fetched + kept))
    result: Dict[str, Any] = {"task": task, "fetched": [f"{task}/{tasks.DEV_NAME}/{key}" for key in fetched], "total_fetched": len(data["target_files"])}
    if kept:
        result["kept"] = kept
        result["note"] = "这些文件在 DEV/ 里已经改过，没有覆盖。要丢掉改动重新取，加 --overwrite。"
    return result


def delete(root: Path, raw_task: str, specs: List[str]) -> Dict[str, Any]:
    if not specs:
        raise CommandError("要写 `<仓库名>/<路径>`。")
    task = resolve(root, raw_task)
    with locked(root, task) as data:
        require_open(data)
        require_plan(root, task, data)
        if not data.get("target_mode"):
            raise CommandError("没有配置目标仓库，回写不能删文件。")
        found = ops.load_targets(root)
        for spec in specs:
            key = layout.relative_name(spec, "要删的文件")
            ops.check_target_output(found, key, "delete")
            if key not in data["target_files"]:
                raise CommandError(f"`{key}` 不是这个任务从 main 取过的文件。先 `task fetch {key}`，再 `task delete {key}`。")
            copy = tasks.dev_dir(root, task) / key
            if copy.is_file():
                ops.writable(copy)
                copy.unlink()
            if key not in data["deletes"]:
                data["deletes"].append(key)
        if data["promote"]["state"] == "dry_run":
            data["promote"] = {"state": "none"}
        note(data, "delete", "、".join(specs))
    return {"task": task, "deletes": data["deletes"], "next": "改名或移动：新路径的文件直接建在 DEV/ 下。"}


def dev_files(root: Path, task: str) -> List[Tuple[str, Path]]:
    """(key, file) of every result file under DEV/, sorted. Backups promote put there (`_deleted/`, `*.patch`) are not results."""
    dev = tasks.dev_dir(root, task)
    found: List[Tuple[str, Path]] = []
    for current, folders, files in os.walk(str(dev)):
        top = Path(current) == dev
        folders[:] = sorted(name for name in folders if name not in ops.SKIP_NAMES and not (top and name in SKIP_TOP))
        for name in sorted(files):
            if name in ops.SKIP_NAMES or (top and name.endswith(".patch")):
                continue
            path = Path(current) / name
            found.append((path.relative_to(dev).as_posix(), path))
    return found


def _text(blob: bytes) -> Optional[List[str]]:
    try:
        return blob.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


def changes(root: Path, task: str, data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    """What DEV/ changes against the fetched versions: one entry per file, and the whole thing as a unified diff."""
    base = tasks.base_dir(root, task)
    items: List[Dict[str, Any]] = []
    out: List[str] = [f"# 任务 {task} 第 {data['round']} 轮：DEV/ 和取文件时 main 上版本的差异。只列改动的行，每处带 3 行上下文。"]
    for key, path in dev_files(root, task):
        new = path.read_bytes()
        old_path = base / key
        old = old_path.read_bytes() if old_path.is_file() and key in data["target_files"] else None
        if old == new:
            items.append({"path": key, "action": "unchanged", "added": 0, "removed": 0})
            continue
        before, after = (_text(old) if old is not None else []), _text(new)
        out.append(f"diff --git a/{key} b/{key}")
        if before is None or after is None:
            out.append("（二进制文件，不显示差异）")
            items.append({"path": key, "action": "modify" if old is not None else "create", "added": 0, "removed": 0})
            continue
        if old is None:
            out += ["--- /dev/null", f"+++ b/{key}"] + ["+" + line for line in after]
            items.append({"path": key, "action": "create", "added": len(after), "removed": 0})
            continue
        lines = list(difflib.unified_diff(before, after, f"a/{key}", f"b/{key}", lineterm="", n=3))
        out += lines
        items.append({
            "path": key, "action": "modify",
            "added": sum(1 for line in lines if line.startswith("+") and not line.startswith("+++")),
            "removed": sum(1 for line in lines if line.startswith("-") and not line.startswith("---")),
        })
    for key in data["deletes"]:
        old_path = base / key
        before = _text(old_path.read_bytes()) if old_path.is_file() else []
        out += [f"diff --git a/{key} b/{key}", "deleted file", f"--- a/{key}", "+++ /dev/null"]
        out += ["-" + line for line in before] if before is not None else ["（二进制文件，不显示内容）"]
        items.append({"path": key, "action": "delete", "added": 0, "removed": len(before or [])})
    return items, "\n".join(out) + "\n"


def diff(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = resolve(root, raw_task)
    data = read(root, task)
    items, text = changes(root, task, data)
    path = tasks.task_dir(root, task) / tasks.CHANGES_NAME
    ops.write_text(path, text)
    changed = [item for item in items if item["action"] != "unchanged"]
    return {
        "task": task, "files": changed, "unchanged": len(items) - len(changed) + 0, "diff_file": rel(root, path),
        "next": "差异全文在 diff_file 里。verifier 复核时让它读这个文件、REQ/ 和 PLAN.md，不用读整份成果。",
    }


# --- promote -------------------------------------------------------------------------------------


def review_path(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task) / tasks.REVIEW_NAME


def approve_command(task: str) -> str:
    return f"{cli_command()} task approve-promote --task {task}"


def recover_command(task: str) -> str:
    return f"{cli_command()} task recover --task {task}"


def patch_name(data: Dict[str, Any]) -> str:
    return data["name"] + (f"_r{data['round']}" if data["round"] > 1 else "") + ".patch"


def header(task: str, data: Dict[str, Any]) -> str:
    return f"# task {task}, round {data['round']}, branch {data.get('branch', '')}"


def make_plan(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if not data.get("target_mode"):
        raise CommandError("没有配置目标仓库，没有地方可回写。成果就在 DEV/ 下，做完 `task close`。")
    found = dev_files(root, task)
    loose = [key for key, _path in found if "/" not in key]  # directly in DEV/: under no repository, so it is not written back
    items: List[Dict[str, Any]] = [{"key": key, "source": path, "sha256": store.sha256_file(path), "delete": False} for key, path in found if "/" in key]
    clash = [item["key"] for item in items if item["key"] in data["deletes"]]
    if clash:
        raise CommandError(f"`{clash[0]}` 已经声明删除，但 DEV/ 里又有这个文件。二选一：删掉 DEV/ 里的文件，或 `task fetch {clash[0]}` 取消删除。")
    items += [{"key": key, "source": None, "sha256": "", "delete": True} for key in data["deletes"]]
    if not items:
        raise CommandError(
            "DEV/ 里没有要回写的成果，没有东西可回写。"
            + (f"直接放在 DEV/ 根目录的文件不回写（{'、'.join(loose)}）；要回写的放到 DEV/<仓库名>/<路径> 下。" if loose else "")
        )
    branch = data.get("branch", "")
    repos, files = promote_target.plan_files(root, items, data["target_files"], branch, HINTS)
    result: Dict[str, Any] = {
        "task": task, "round": data["round"], "branch": branch, "repos": repos, "files": files,
        "plan_sha256": promote_target.plan_digest(branch, repos, files),
    }
    if loose:
        result["not_promoted"] = loose
        result["not_promoted_note"] = "这些文件直接放在 DEV/ 根目录，不属于任何目标仓库，不会回写。要回写，放到 DEV/<仓库名>/<路径> 下。"
    return result


def write_review(root: Path, task: str, data: Dict[str, Any], result: Dict[str, Any]) -> str:
    path = review_path(root, task)
    ops.write_text(path, promote_target.full_patch(root, result, header(task, data)))
    return rel(root, path)


def run_promote(root: Path, raw_task: str, dry_run: bool) -> Dict[str, Any]:
    task = resolve(root, raw_task)
    with locked(root, task) as data:
        require_open(data)
        require_plan(root, task, data)
        record = data["promote"]
        if record["state"] == "done":
            raise CommandError("这一轮已经 promote 过了，不再回写第二次。要再改，重新 `task start` 开新的一轮（要新计划、新批准）。")
        if record["state"] == "partial":
            raise CommandError(f"上次 promote 中途出错，仓库可能还是半成品。先请用户在自己的终端运行 `{recover_command(task)}`，再重新 --dry-run、批准。")
        result = make_plan(root, task, data)
        if dry_run:
            new = {"state": "dry_run", "plan_sha256": result["plan_sha256"], "at": utc_now()}
            if record.get("approved_plan_sha256") == result["plan_sha256"]:
                new.update(approved_plan_sha256=record["approved_plan_sha256"], approved_at=record["approved_at"])  # same plan: keep the approval
            data["promote"] = new
            note(data, "promote-dry-run", result["plan_sha256"][:12])
            result["approved"] = "approved_plan_sha256" in new
            result["review_file"] = write_review(root, task, data, result)
            result["next"] = (
                "已经有用户的批准，可以运行 task promote（去掉 --dry-run）。"
                if result["approved"]
                else f"告诉用户：完整差异在 [{tasks.REVIEW_NAME}]({result['review_file']})（给出这个链接，让用户在编辑器里打开看，不要把差异贴进对话）。"
                "看完后请用户在自己的终端运行：" + approve_command(task) + "，输入确认码。用户批准后，再运行 task promote（去掉 --dry-run）。"
            )
            return {"dry_run": True, **promote.shown(result)}
        if record["state"] != "dry_run" or record.get("plan_sha256") != result["plan_sha256"]:
            raise CommandError("还没有对应的 --dry-run，或者 DEV/、仓库在 dry-run 之后变了。先重新运行 --dry-run，让用户看过再批准。")
        if record.get("approved_plan_sha256") != result["plan_sha256"]:
            raise CommandError(
                "用户还没有批准这份回写计划。请用户在自己的终端运行：" + approve_command(task)
                + "，在编辑器里看完差异，按提示输入确认码。你不能自己运行它。用户说批准了，再运行 task promote。"
            )
        new, failed = promote_target.run_result(
            root, result, tasks.dev_dir(root, task), patch_name(data), record, recover_command(task), header(task, data),
        )
        data["promote"] = new  # a `partial` record is saved too: the lock writes it back, the error is raised after
        note(data, "promote" if not failed else "promote-partial", result["branch"])
        if not failed:
            result["next"] = (
                f"已写到各仓库的新分支 {result['branch']}，文件没有提交，补丁在 {new['patch']}。"
                "告诉用户：在每个仓库里检查改动、自己 commit。然后 `task close`。"
            )
            return {"dry_run": False, **promote.shown(result)}
        failure = promote_target.partial_message(new)
    raise CommandError(failure)


def approve_promote(
    root: Path, raw_task: str = "", reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None,
) -> Dict[str, Any]:
    person("approve-promote", interactive)
    task = resolve(root, raw_task, lambda item: item["promote"]["state"] == "dry_run" and "approved_plan_sha256" not in item["promote"], "等待批准回写的")
    data = read(root, task)
    require_open(data)
    if data["promote"]["state"] != "dry_run":
        raise CommandError("还没有 --dry-run 的计划，或者已经 promote 过。先让 agent 运行 task promote --dry-run。")
    result = make_plan(root, task, data)
    if result["plan_sha256"] != data["promote"]["plan_sha256"]:
        raise CommandError("DEV/ 或仓库在 dry-run 之后变了。让 agent 重新运行 task promote --dry-run，再来批准。")
    review = write_review(root, task, data, result)  # written again now: it is what gets approved
    lines = [f"任务 {task}（第 {data['round']} 轮）。将回写这些文件："]
    for repo in result["repos"]:
        lines.append(f"  仓库 {repo['name']}（{repo['path']}）：从 {repo['base_ref']}（{repo['base_commit'][:12]}）新建分支 {result['branch']}，写入文件，不提交。")
    if any(item["action"] == "delete" for item in result["files"]):
        lines.append("  注意：标着 delete 的文件会被删除。")
    lines += [f"  {item['action']:9} {item['path']}  (+{item['added']} -{item['removed']})" for item in result["files"]]
    if result.get("not_promoted"):
        lines.append("  不回写（直接放在 DEV/ 根目录，不属于任何仓库）：" + "、".join(result["not_promoted"]))
    lines.append(f"完整差异在这个文件里，先在编辑器里打开看：{review}")
    approval.say(out, *lines)
    typed("确认回写", result["plan_sha256"], "没有批准。什么都没有写。", reader)
    with locked(root, task) as again:
        require_open(again)
        check = make_plan(root, task, again)
        if check["plan_sha256"] != result["plan_sha256"] or again["promote"].get("plan_sha256") != result["plan_sha256"]:
            raise CommandError("你确认的时候计划变了。让 agent 重新运行 task promote --dry-run，再来批准。")
        again["promote"]["approved_plan_sha256"] = result["plan_sha256"]
        again["promote"]["approved_at"] = utc_now()
        note(again, "approve-promote", result["plan_sha256"][:12])
    return {"approved": True, "task": task, "files": len(result["files"]), "review_file": review, "next": "告诉 agent 可以运行 task promote 了。"}


def recover(
    root: Path, raw_task: str = "", reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None,
) -> Dict[str, Any]:
    """The person puts the repositories back after a task promote that stopped halfway. The steps are the ones of the L3 recover."""
    person("recover", interactive)
    task = resolve(root, raw_task, lambda item: item["promote"]["state"] == "partial", "promote 中途出错的")
    data = read(root, task)
    record = data["promote"]
    if record["state"] != "partial":
        raise CommandError("这个任务的 promote 没有中途出错，不需要恢复。")
    lines = [f"任务 {task}：promote 中途出错（出错的仓库 {record.get('repo_failed', '')}：{record.get('error', '')}）。将运行："]
    lines += [f"  {command}" for command in record.get("recovery", [])] or ["  （没有要运行的命令：没有仓库被改动）"]
    approval.say(out, *lines)
    typed("确认恢复", record["plan_sha256"], "没有确认。什么都没有做。", reader)
    found = ops.load_targets(root)
    results = promote_target.run_recovery(record["recovery_steps"], record["branch"], found.timeout)
    approval.say(out, *[f"  [{item['status']}] {item['command']}" + (f"  {item['message']}" if item["message"] else "") for item in results])
    failed = [item for item in results if item["status"] == "failed"]
    if failed:
        raise CommandError(f"{len(failed)} 步没有成功（上面标 [failed] 的）。先按 git 的提示处理（例如文件夹只读、文件被占用），再运行一次 recover：已经做完的步骤会跳过。")
    with locked(root, task) as again:
        again["promote"] = {"state": "none", "recovered_at": utc_now()}
        note(again, "recover")
    counts = {name: sum(1 for item in results if item["status"] == name) for name in ("done", "skipped")}
    return {"recovered": True, "task": task, **counts, "next": "仓库已经恢复。让 agent 重新运行 task promote --dry-run，用户再批准。"}
