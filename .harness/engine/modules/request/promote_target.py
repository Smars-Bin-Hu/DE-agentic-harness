"""promote for a request with target repositories (B10-A3): the reviewed result goes onto a new branch of each repository.

The plan is checked for every repository before anything is written: a clean working tree, a branch name that is free,
and files whose version on the base branch is still the one the request copied (new files must not exist there yet).
Only when all repositories pass does the real run start. Per repository it makes the branch from the base branch and
writes the files. It never commits, never resets, never switches back: the person reviews the files and commits them.

Before the first repository is touched, the result is also saved to `<task>/DEV/<repo>/<path>` with a patch
`<task>/DEV/<request id>.patch` (the request folder's own `DEV` when the request has no task).
When a step fails halfway there is no automatic undo across repositories: the run stops, the request is marked `partial`,
and the message says what is done, what is not, and the commands that put each touched repository back.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import repo_paths, targets
from core.paths import cli_command, utc_now

from . import layout, ops, store
from .layout import CommandError

DIFF_PREVIEW_LINES = 40
ALWAYS_REFUSED = (".git/**",)
PROBLEMS_SHOWN = 6
# Words of the refusals that differ between an L3 request and an L2 task (the task module passes its own).
REQUEST_HINTS = {
    "fetch": "用 `--from-target {key}` 取过再改。",
    "refetch": "重新取文件，重新走一轮。",
    "set_branch": "先 `request set-branch --request <id> --branch feature/<名字>`。",
    "rename_branch": "换一个分支名（`request set-branch`），或先处理掉那个分支。",
    "drop": "把它从成果里去掉，重新评审。",
}


def _lines(blob: bytes) -> int:
    try:
        return len(blob.decode("utf-8").splitlines())
    except UnicodeDecodeError:
        return 0


def _diff(old: bytes, new: bytes, name: str) -> Dict[str, Any]:
    try:
        before, after = old.decode("utf-8").splitlines(), new.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return {"added": 0, "removed": 0, "diff": ["（二进制文件，不显示差异）"]}
    lines = list(difflib.unified_diff(before, after, f"a/{name}", f"b/{name}", lineterm="", n=1))
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return {"added": added, "removed": removed, "diff": lines[:DIFF_PREVIEW_LINES]}


def _names_in(repo: targets.Repo, commit: str, folder: str, timeout: int) -> List[Tuple[str, str]]:
    """(type, name) of what `commit` has directly in `folder` ("" is the top)."""
    spec = [f"{folder}/"] if folder else []
    raw = targets.git(repo, "ls-tree", "-z", commit, "--", *spec, timeout=timeout).decode("utf-8", errors="replace")
    found = []
    for line in raw.split("\0"):
        if line:
            info, _, path = line.partition("\t")
            found.append((info.split(" ")[1], path.rsplit("/", 1)[-1]))
    return found


def _file_problem(
    repo: targets.Repo, commit: str, relative: str, key: str, target_files: Dict[str, Any], timeout: int, hints: Dict[str, str],
) -> Tuple[str, str, Optional[bytes]]:
    """(problem, "", None) or ("", blob of the base branch or "", its bytes). "" blob means a new file."""
    recorded = target_files.get(key)
    listed = targets.tracked_files(repo, commit, relative, timeout)
    exact = [item for item in listed if item[2] == relative]
    if listed and not exact:
        return f"`{key}` 在 {repo.base_ref} 上是一个文件夹。", "", None
    if exact:
        mode, blob, _path = exact[0]
        if mode not in targets.REGULAR_FILE_MODES:
            return f"`{key}` 在 {repo.base_ref} 上不是普通文件（符号链接或子模块）。", "", None
        if recorded is None:
            return f"`{key}` 在 {repo.base_ref} 上已经有了，但这个请求没有从 {repo.base_ref} 取过它，不知道成果是基于哪一版改的。" + hints["fetch"].format(key=key), "", None
        if recorded["blob"] != blob:
            return (
                f"`{key}` 在 {repo.base_ref} 上变了：这个请求取走它时是 {recorded['blob'][:10]}，现在是 {blob[:10]}。"
                "成果是基于旧版本改的，直接回写会丢掉别人的改动。" + hints["refetch"]
            ), "", None
        return "", blob, targets.read_blob(repo, blob, timeout)
    if recorded is not None:
        return f"`{key}` 是这个请求从 {repo.base_ref} 取走的，现在 {repo.base_ref} 上没有了（被删除或改名）。", "", None
    parts = relative.split("/")
    for index in range(1, len(parts)):  # a file (or link) where a folder is needed
        folder = "/".join(parts[: index - 1])
        names = _names_in(repo, commit, folder, timeout)
        clash = [kind for kind, name in names if name == parts[index - 1]]
        if clash and clash != ["tree"]:
            return f"`{key}` 的上级 `{'/'.join(parts[:index])}` 在 {repo.base_ref} 上是文件，不能在它下面建文件。", "", None
        for _kind, name in names:
            if name != parts[index - 1] and name.lower() == parts[index - 1].lower():
                return f"`{key}` 的上级 `{parts[index - 1]}` 和 {repo.base_ref} 上的 `{name}` 只差大小写。macOS 和 Windows 的文件系统会把它们当成同一个文件夹。", "", None
    for kind, name in _names_in(repo, commit, "/".join(parts[:-1]), timeout):  # same name in another letter case
        if name != parts[-1] and name.lower() == parts[-1].lower():
            return f"`{key}` 和 {repo.base_ref} 上的 `{name}` 只差大小写。macOS 和 Windows 的文件系统会把它们当成同一个文件，直接写会盖掉 `{name}`。", "", None
    return "", "", None


def plan(root: Path, request_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    directory = layout.request_dir(root, request_id)
    number = data["attempt"]
    if number < 1 or data["attempts"][-1]["handoffs"].get("reviewer") != "passed":
        raise CommandError("最后一轮 reviewer 还不是 passed，不能 promote。先走完评审；不通过就 `attempt new` 返工。")
    package = layout.package_dir(directory, number, "reviewer")
    manifest = ops.store_json(package / "manifest.json")
    candidates = [item for item in manifest["files"] if item["purpose"] in ("candidate", "deleted")]
    if not candidates:
        raise CommandError("reviewer 评审的输入包里没有成果文件，没有东西可回写。")
    items: List[Dict[str, Any]] = []
    for item in candidates:
        source = package / item["path"]
        if not source.is_file() or store.sha256_file(source) != item["sha256"]:
            raise CommandError(f"评审过的文件 `{item['path']}` 被改动或丢了（和 manifest 的 sha256 不一致）。重新走一轮评审。")
        key = layout.relative_name(item["path"].split("/", 1)[1], "成果路径")  # drop the leading `candidate/` (or `base/`)
        items.append({"key": key, "source": source, "sha256": item["sha256"], "delete": item["purpose"] == "deleted"})
    branch = data.get("branch", "")
    repos, files = plan_files(root, items, data.get("target_files", {}), branch, REQUEST_HINTS)
    return {"request_id": request_id, "attempt": number, "branch": branch, "repos": repos, "files": files, "plan_sha256": plan_digest(branch, repos, files)}


def plan_digest(branch: str, repos: List[Dict[str, Any]], files: List[Dict[str, Any]]) -> str:
    return store.sha256_text(json.dumps([
        branch, [[r["name"], r["base_commit"]] for r in repos], [[f["path"], f["action"], f["sha256"]] for f in files],
    ]))


def plan_files(
    root: Path, items: List[Dict[str, Any]], target_files: Dict[str, Any], branch: str, hints: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Check every repository and file of a result. `items`: {key `<repo>/<path>`, source file, sha256, delete}.

    Returns (repos, files) when everything passes; raises CommandError listing every problem otherwise. Nothing is written.
    """
    found = ops.load_targets(root)
    problems: List[str] = []
    if not branch:
        problems.append("还没有分支名。" + hints["set_branch"])
    elif not targets.valid_branch(branch):
        problems.append(f"分支名 `{branch}` 不合规（`feature/` 加字母、数字、下划线）。" + hints["set_branch"])
    by_repo: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        name, _, relative = item["key"].partition("/")
        by_repo.setdefault(name, []).append({**item, "relative": relative})
    repos: List[Dict[str, Any]] = []
    files: List[Dict[str, Any]] = []
    for name in sorted(by_repo):
        if name not in found.repos or not by_repo[name][0]["relative"]:
            problems.append(f"成果的第一段 `{name}` 不是已配置的目标仓库（已知：{'、'.join(found.names()) or '没有'}）。")
            continue
        repo = found.repos[name]
        timeout = found.timeout
        mine: List[str] = []
        try:
            commit = targets.ref_commit(repo, timeout)
            if not commit:
                mine.append(f"本地没有分支 `{repo.base_ref}`。")
            else:
                dirty = targets.dirty_paths(repo, timeout)
                if dirty:
                    shown = "、".join(dirty[:PROBLEMS_SHOWN]) + (f" 等 {len(dirty)} 个" if len(dirty) > PROBLEMS_SHOWN else "")
                    mine.append(f"工作区不干净（{shown}）。先提交、stash 或丢弃这些改动，再 promote。")
                if branch and targets.valid_branch(branch) and targets.git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", timeout=timeout, allow_failure=True).strip():
                    mine.append(f"分支 `{branch}` 已经存在。" + hints["rename_branch"])
        except targets.TargetError as error:
            problems.append(f"{name}：{error}")
            continue
        entries: List[Dict[str, Any]] = []
        for item in by_repo[name]:
            key, relative = item["key"], item["relative"]
            refused = [pattern for pattern in list(ALWAYS_REFUSED) + list(repo.refused_paths) if repo_paths.glob_regex(pattern).match(relative)]
            if refused:
                mine.append(f"成果里有 `{key}`，它属于不能回写的路径（{refused[0]}）。" + hints["drop"])
                continue
            if not commit:
                continue
            try:
                problem, blob, old_bytes = _file_problem(repo, commit, relative, key, target_files, timeout, hints)
            except targets.TargetError as error:
                mine.append(str(error))
                continue
            if problem:
                mine.append(problem)
                continue
            entry: Dict[str, Any] = {"path": key, "repo": name, "relative": relative, "sha256": item["sha256"]}
            if item["delete"]:
                if old_bytes is None:
                    mine.append(f"`{key}` 在 {repo.base_ref} 上不存在，没有东西可删。")
                    continue
                entry.update(action="delete", base_blob=blob, **_diff(old_bytes, b"", key))
                entries.append(entry)
                continue
            new_bytes = item["source"].read_bytes()
            entry["source"] = str(item["source"])
            if old_bytes is None:
                entry.update(action="create", added=_lines(new_bytes), removed=0, diff=[])
            elif old_bytes == new_bytes:
                entry.update(action="unchanged", added=0, removed=0, diff=[])
            else:
                entry.update(action="modify", base_blob=blob, **_diff(old_bytes, new_bytes, key))
            entries.append(entry)
        if not mine and all(item["action"] == "unchanged" for item in entries):
            mine.append(f"成果和 {repo.base_ref} 上的文件完全一样，没有东西可回写。")
        problems += [f"{name}：{text}" for text in mine]
        if not mine:
            repos.append({
                "name": name, "path": str(repo.path), "base_ref": repo.base_ref, "base_commit": commit,
                "current_branch": targets.current_branch(repo, timeout), "files": entries,
            })
            files += entries
    if problems:
        raise CommandError("现在不能 promote，没有写任何东西。先解决这些，再重新 --dry-run：\n" + "\n".join(f"- {text}" for text in problems))
    return repos, files


# --- the real run ---------------------------------------------------------------------------------


def dev_root(root: Path, data: Dict[str, Any], request_id: str) -> Path:
    task = data.get("task", "")
    return (root / task / "DEV") if task else layout.request_dir(root, request_id) / "DEV"


def full_patch(root: Path, result: Dict[str, Any], header: str = "") -> str:
    """The whole change as one unified diff (the plan keeps only a preview). Also what a person reads before approving."""
    out: List[str] = [header or f"# request {result.get('request_id', '')}, branch {result['branch']}"]
    found = ops.load_targets(root)
    for repo in result["repos"]:
        out.append(f"# repository {repo['name']}: {repo['base_ref']} at {repo['base_commit']}")
    for item in result["files"]:
        if item["action"] == "unchanged":
            continue
        out.append(f"diff --git a/{item['path']} b/{item['path']}")
        if item["action"] == "delete":
            out += ["deleted file", f"--- a/{item['path']}", "+++ /dev/null"]
            try:
                out += ["-" + line for line in old_content(found, item).decode("utf-8").splitlines()]
            except UnicodeDecodeError:
                out.append("（二进制文件，不显示内容）")
            continue
        new_bytes = Path(item["source"]).read_bytes()
        if item["action"] == "create":
            out.append("--- /dev/null")
            out.append(f"+++ b/{item['path']}")
            try:
                out += ["+" + line for line in new_bytes.decode("utf-8").splitlines()]
            except UnicodeDecodeError:
                out.append("（二进制文件，不显示内容）")
            continue
        try:
            before, after = old_content(found, item).decode("utf-8").splitlines(), new_bytes.decode("utf-8").splitlines()
            out += list(difflib.unified_diff(before, after, f"a/{item['path']}", f"b/{item['path']}", lineterm="", n=3))
        except UnicodeDecodeError:
            out.append("（二进制文件，不显示差异）")
    return "\n".join(out) + "\n"


def old_content(found: targets.Targets, item: Dict[str, Any]) -> bytes:
    """The version of a modified or deleted file on the base branch, read by its blob."""
    return targets.read_blob(found.repos[item["repo"]], item["base_blob"], found.timeout)


def save_dev(root: Path, base: Path, patch_name: str, result: Dict[str, Any], header: str = "") -> Dict[str, str]:
    """Back the result up under `base` (a DEV folder) before any repository is touched. A source already there is left alone."""
    try:
        found = ops.load_targets(root)
        for item in result["files"]:
            if item["action"] == "delete":  # keep the file that goes away, apart from the results
                destination = base / "_deleted" / item["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(old_content(found, item))
            elif Path(item["source"]).resolve() != (base / item["path"]).resolve():
                ops.copy_file(Path(item["source"]), base / item["path"])
        patch = base / patch_name
        patch.parent.mkdir(parents=True, exist_ok=True)
        patch.write_text(full_patch(root, result, header), encoding="utf-8")
    except (OSError, targets.TargetError) as error:
        raise CommandError(f"备份到 DEV 目录失败（{error}）。仓库一个都没有改。") from error
    return {"dev": layout.inside(root, base) or str(base), "patch": layout.inside(root, patch) or str(patch)}


def quote(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'


def render(step: Dict[str, Any]) -> str:
    """A recovery step as one command line a person can paste: the paths and names in double quotes."""
    first, *rest = step["git"]
    shown = " ".join(item if item.startswith("-") else quote(item) for item in rest)
    return f"git -C {quote(step['repo'])} {first}" + (f" {shown}" if shown else "")


def recovery_steps(repo: Dict[str, Any], branch: str, switched: bool, written: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The steps that put one repository back as it was: the written files, the checkout, the branch."""
    path = repo["path"]
    steps = []
    modified = [item["relative"] for item in written if item["action"] in ("modify", "delete")]  # a deleted file comes back with `restore`
    created = [item["relative"] for item in written if item["action"] == "create"]
    if modified:
        steps.append({"repo": path, "git": ["restore", "--", *modified]})
    if created:
        steps.append({"repo": path, "git": ["clean", "-f", "--", *created]})
    if switched:
        original = repo["current_branch"] if repo["current_branch"] != "(detached)" else repo["base_ref"]
        steps.append({"repo": path, "git": ["switch", original]})
        steps.append({"repo": path, "git": ["branch", "-d", branch]})
    return steps


def recovery_commands(repo: Dict[str, Any], branch: str, switched: bool, written: List[Dict[str, Any]]) -> List[str]:
    return [render(step) for step in recovery_steps(repo, branch, switched, written)]


def run_recovery(steps: List[Dict[str, Any]], branch: str, timeout: int) -> List[Dict[str, Any]]:
    """Run the steps of a `partial` record, repository by repository. Returns one result per step: command, status, message.

    Only a repository that is still on the promote branch gets its files restored and its checkout changed: a person who
    already switched back may have edits of their own in those files. The branch is deleted when it still exists (`-d`: git
    refuses when it holds commits that no other branch has). A step that fails ends that repository's steps, not the others.
    """
    results: List[Dict[str, Any]] = []
    by_repo: Dict[str, List[Dict[str, Any]]] = {}
    for step in steps:
        by_repo.setdefault(step["repo"], []).append(step)
    for path, own in by_repo.items():
        on_branch = targets.run_step(Path(path), ["symbolic-ref", "--short", "-q", "HEAD"], timeout)[1] == branch
        stopped = False
        for step in own:
            result = {"command": render(step), "status": "", "message": ""}
            results.append(result)
            verb = step["git"][0]
            if stopped:
                result["status"] = "skipped"
                result["message"] = "这个仓库前面的一步失败了。"
                continue
            if verb in ("restore", "clean", "switch") and not on_branch:
                result["status"] = "skipped"
                result["message"] = f"仓库已经不在分支 {branch} 上，不动它的文件和当前分支。"
                continue
            if verb == "branch":
                exists = targets.run_step(Path(path), ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], timeout)[0] == 0
                if not exists:
                    result["status"] = "skipped"
                    result["message"] = f"分支 {branch} 已经不存在。"
                    continue
            code, said = targets.run_step(Path(path), step["git"], timeout)
            result["status"], result["message"] = ("done", said) if code == 0 else ("failed", said)
            stopped = code != 0
    return results


def prune_empty_folders(top: Path, folder: Path) -> None:
    """After a delete: git does not track folders, so a folder that lost its last file goes too. Stops at the repository top."""
    while folder != top and folder.is_dir():
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent


def write_repo(root: Path, found: targets.Targets, repo: Dict[str, Any], branch: str, written: List[Dict[str, Any]]) -> bool:
    """Make the branch and write the files of one repository. Returns whether the branch was made; fills `written`."""
    handle = found.repos[repo["name"]]
    targets.git(handle, "switch", "-c", branch, handle.base_ref, timeout=found.timeout)
    top = handle.path.resolve()
    for item in repo["files"]:
        if item["action"] == "unchanged":
            continue
        destination = handle.path / item["relative"]
        if layout.inside(top, destination) is None:
            raise OSError(f"`{item['relative']}` 指向仓库之外")
        written.append(item)  # before the write: a half-written file is undone like a finished one
        if item["action"] == "delete":
            destination.unlink()
            prune_empty_folders(handle.path, destination.parent)
            if destination.exists():
                raise OSError(f"`{item['relative']}` 没有被删掉")
            continue
        ops.copy_file(Path(item["source"]), destination)
        if store.sha256_file(destination) != item["sha256"]:
            raise OSError(f"写入后 `{item['relative']}` 的内容和成果不一致")
    return True


def run(root: Path, data: Dict[str, Any], request_id: str, result: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """An L3 request: write the planned result. See `run_result`."""
    recover = f"{cli_command()} request recover --request {request_id}"
    return run_result(root, result, dev_root(root, data, request_id), f"{request_id}.patch", data["promote"], recover)


def run_result(
    root: Path, result: Dict[str, Any], base: Path, patch_name: str, approval: Dict[str, Any], recover: str, header: str = "",
) -> Tuple[Dict[str, Any], str]:
    """Write the planned result. Returns (promote record, message). `message` is empty on success; otherwise the run failed
    halfway, the record is `partial`, and the message tells the person what to do."""
    found = ops.load_targets(root)
    saved = save_dev(root, base, patch_name, result, header)
    branch = result["branch"]
    done: List[str] = []
    for index, repo in enumerate(result["repos"]):
        written: List[Dict[str, Any]] = []
        switched = False
        try:
            switched = write_repo(root, found, repo, branch, written)
        except (OSError, targets.TargetError, CommandError) as error:
            # `switch -c` may have worked before the failure: ask git, do not guess
            try:
                switched = switched or targets.current_branch(found.repos[repo["name"]], found.timeout) == branch
            except targets.TargetError:
                switched = False
            return partial_record(result, saved, done, repo, written, switched, error, result["repos"][index + 1:], recover), "partial"
        done.append(repo["name"])
    record = {
        "state": "done",
        "plan_sha256": result["plan_sha256"],
        "approved_plan_sha256": approval["approved_plan_sha256"],
        "approved_at": approval["approved_at"],
        "at": utc_now(),
        "branch": branch,
        "repos": {repo["name"]: {"path": repo["path"], "base_commit": repo["base_commit"], "current_branch": repo["current_branch"]} for repo in result["repos"]},
        "files": [{"path": f["path"], "action": f["action"], "sha256": f["sha256"]} for f in result["files"]],
        **saved,
    }
    return record, ""


def partial_record(
    result: Dict[str, Any], saved: Dict[str, str], done: List[str],
    failed: Dict[str, Any], written: List[Dict[str, Any]], switched: bool, error: Exception, rest: List[Dict[str, Any]], recover: str,
) -> Dict[str, Any]:
    branch = result["branch"]
    by_name = {repo["name"]: repo for repo in result["repos"]}
    steps: List[Dict[str, Any]] = []
    for name in done:
        steps += recovery_steps(by_name[name], branch, True, [f for f in by_name[name]["files"] if f["action"] != "unchanged"])
    steps += recovery_steps(failed, branch, switched, written)
    return {
        "state": "partial",
        "request_id": result.get("request_id", ""),
        "recover_command": recover,
        "plan_sha256": result["plan_sha256"],
        "at": utc_now(),
        "branch": branch,
        "error": str(error),
        "repos_done": done,
        "repo_failed": failed["name"],
        "repos_untouched": [repo["name"] for repo in rest],
        "recovery": [render(step) for step in steps],
        "recovery_steps": steps,
        **saved,
    }


def partial_message(record: Dict[str, Any]) -> str:
    done = "、".join(record["repos_done"]) or "（没有）"
    untouched = "、".join(record["repos_untouched"]) or "（没有）"
    lines = [
        f"promote 中途出错，已经停下，没有自动恢复。出错的仓库：{record['repo_failed']}。原因：{record['error']}",
        f"- 已经写好的仓库（在新分支 {record['branch']} 上，文件没有提交）：{done}",
        f"- 出错的仓库：{record['repo_failed']}（可能写了一部分）",
        f"- 没有动过的仓库：{untouched}",
        f"- 成果和补丁已经备份在 {record['dev']}。",
    ]
    if record["recovery"]:
        recover = record.get("recover_command") or f"{cli_command()} request recover --request {record['request_id']}"
        lines.append(f"把仓库恢复成原样：请用户在自己的终端运行 `{recover}`（看清要做的事，输入确认码，它逐条运行）。")
        lines.append("也可以自己逐条运行下面的命令：")
        lines += [f"    {command}" for command in record["recovery"]]
    lines.append("恢复后，让 agent 重新 `promote --dry-run`，用户再批准。不要自己结束请求或任务。")
    return "\n".join(lines)
