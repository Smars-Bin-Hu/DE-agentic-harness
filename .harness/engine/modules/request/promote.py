"""promote: the one way a result gets back into the repository (design: "受控回写").

Only the files the reviewer saw (to-reviewer/candidate/) are copied, and only when the last reviewer handoff is
`passed`. Candidate paths are repository-relative paths. `--dry-run` shows the plan. The real run needs the person's approval of that same plan, given with
`request approve-promote`: it works only in a terminal the person types in (stdin and stdout are a TTY) and asks them to
type a code from the plan. A tool-call dialog cannot be the guard, because "Allow in this Session" switches it off.
The gate also denies an agent that tries to run `approve-promote`.
The person reads the change in the editor, not in the terminal: `--dry-run` writes the whole diff to `promote-plan.diff` in
the request folder (a file only the CLI writes), and the approval screen only lists the files and names that file.
A request with target repositories is planned and written by `promote_target.py`: the result goes onto a new branch of each
repository (never committed), and nothing is written unless every repository passes its checks.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import approval, config, repo_paths
from core.guardrails import guardrail_paths
from core.paths import cli_command, utc_now

from . import layout, ops, promote_target, store
from .layout import CommandError

DIFF_PREVIEW_LINES = 40
ALWAYS_REFUSED = (".git/**", ".workspace/**")
REVIEW_FILE = "promote-plan.diff"


def refused_patterns(root: Path) -> List[Tuple[str, Any]]:
    """Targets promote must never write: the gate's guardrail and CLI-owned files, plus `.git` and `.workspace`."""
    try:
        gate = config.load_policy(root, "gate")
        names = guardrail_paths(gate) + list(gate.get("cli_owned_paths", []))
    except Exception as error:
        raise CommandError(f"读不了 gate.json（{error}），promote 不能确认哪些文件不能写，所以拒绝执行。先修好 gate.json。") from error
    return [(name, repo_paths.glob_regex(name)) for name in list(ALWAYS_REFUSED) + names]


def plan(root: Path, request_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    directory = layout.request_dir(root, request_id)
    number = data["attempt"]
    if number < 1 or data["attempts"][-1]["handoffs"].get("reviewer") != "passed":
        raise CommandError("最后一轮 reviewer 还不是 passed，不能 promote。先走完评审；不通过就 `attempt new` 返工。")
    package = layout.package_dir(directory, number, "reviewer")
    manifest = ops.store_json(package / "manifest.json")
    candidates = [item for item in manifest["files"] if item["purpose"] == "candidate"]
    if not candidates:
        raise CommandError("reviewer 评审的输入包里没有成果文件，没有东西可回写。")
    refused = refused_patterns(root)
    items: List[Dict[str, Any]] = []
    for item in candidates:
        source = package / item["path"]
        if not source.is_file() or store.sha256_file(source) != item["sha256"]:
            raise CommandError(f"评审过的文件 `{item['path']}` 被改动或丢了（和 manifest 的 sha256 不一致）。重新走一轮评审。")
        target_name = layout.relative_name(item["path"].split("/", 1)[1], "成果路径")  # drop the leading `candidate/`
        for name, regex in refused:
            if regex.match(target_name):
                raise CommandError(f"成果里有 `{target_name}`，它属于不能回写的路径（{name}）。把它从成果里去掉，重新评审。")
        target = root / target_name
        if layout.inside(root, target) is None:
            raise CommandError(f"成果路径 `{target_name}` 指向仓库之外。")
        new_bytes = source.read_bytes()
        entry: Dict[str, Any] = {"path": target_name, "sha256": item["sha256"], "source": str(source)}
        if not target.exists():
            entry.update(action="create", added=_lines(new_bytes), removed=0, diff=[])
        else:
            old_bytes = target.read_bytes()
            if old_bytes == new_bytes:
                entry.update(action="unchanged", added=0, removed=0, diff=[])
            else:
                entry.update(action="modify", **_diff(old_bytes, new_bytes, target_name))
        items.append(entry)
    return {"request_id": request_id, "attempt": number, "files": items, "plan_sha256": store.sha256_text(json.dumps([[f["path"], f["action"], f["sha256"]] for f in items]))}


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


def make_plan(root: Path, request_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return promote_target.plan(root, request_id, data) if data.get("target_mode") else plan(root, request_id, data)


def shown(result: Dict[str, Any]) -> Dict[str, Any]:
    """The plan as the CLI prints it, for the agent: each file once, with its line counts but without the diff.

    The person sees the diff on the approval screen (`approve-promote`) and in the backup patch; a copy here only costs the agent tokens.
    The per-repository copies in `repos` are for the run.
    """
    out = dict(result)
    if "files" in out:
        out["files"] = [{key: value for key, value in item.items() if key not in ("diff", "source")} for item in out["files"]]
    if "repos" in out:
        out["repos"] = [{key: value for key, value in repo.items() if key != "files"} for repo in out["repos"]]
    return out


def review_text(root: Path, result: Dict[str, Any], targeted: bool) -> str:
    """The whole change as one unified diff, for the person to read in the editor before approving."""
    if targeted:
        return promote_target.full_patch(root, result)
    out = [f"# request {result['request_id']}，第 {result['attempt']} 轮：回写到本仓库"]
    for item in result["files"]:
        if item["action"] == "unchanged":
            continue
        name = item["path"]
        out.append(f"diff --git a/{name} b/{name}")
        new_bytes = Path(item["source"]).read_bytes()
        try:
            after = new_bytes.decode("utf-8").splitlines()
            if item["action"] == "create":
                out += ["--- /dev/null", f"+++ b/{name}"] + ["+" + line for line in after]
            else:
                before = (root / name).read_bytes().decode("utf-8").splitlines()
                out += list(difflib.unified_diff(before, after, f"a/{name}", f"b/{name}", lineterm="", n=3))
        except UnicodeDecodeError:
            out.append("（二进制文件，不显示差异）")
    return "\n".join(out) + "\n"


def write_review(root: Path, request_id: str, result: Dict[str, Any], targeted: bool) -> str:
    """Write `promote-plan.diff` into the request folder. Returns its repository-relative path."""
    path = layout.request_dir(root, request_id) / REVIEW_FILE
    ops.write_text(path, review_text(root, result, targeted))
    return layout.inside(root, path) or str(path)


def approve_command(request_id: str) -> str:
    return f"{cli_command()} request approve-promote --request {request_id}"


def code_of(plan_sha256: str) -> str:
    return plan_sha256[:8]


def waiting_request(root: Path) -> str:
    """The one request that has a promote plan waiting for the person. Raises when there is none or several."""
    waiting = [item["request_id"] for item in ops.list_requests(root, "open")["requests"] if item["waiting_for_approval"]]
    if not waiting:
        raise CommandError("没有等待批准的请求。先让 agent 运行 promote --dry-run；或用 `request list` 看所有请求。")
    if len(waiting) > 1:
        raise CommandError("有好几个请求在等批准：" + "、".join(waiting) + "。用 --request 指定一个。")
    return waiting[0]


def approve(
    root: Path,
    request_id: str = "",
    reader: Optional[Callable[[str], str]] = None,
    interactive: Optional[bool] = None,
    out: Any = None,
) -> Dict[str, Any]:
    """The person approves the plan from the last --dry-run. Only a person at a terminal can: stdin and stdout must be a TTY.

    `reader`, `interactive` and `out` exist so tests can stand in for a person; the CLI passes none of them.
    """
    out = out or sys.stdout
    request_id = request_id or waiting_request(root)
    try:
        approval.require_person("approve-promote", interactive)
    except approval.Refused as error:
        raise CommandError(str(error)) from error
    data = store.read_request(root, request_id)
    store.require_open(data)
    if data["promote"]["state"] != "dry_run":
        raise CommandError("还没有 --dry-run 的计划，或者已经 promote 过。先让 agent 运行 promote --dry-run。")
    result = make_plan(root, request_id, data)
    if result["plan_sha256"] != data["promote"]["plan_sha256"]:
        raise CommandError("成果或仓库在 dry-run 之后变了。让 agent 重新运行 promote --dry-run，再来批准。")
    review = write_review(root, request_id, result, bool(data.get("target_mode")))  # written again now: it is what gets approved
    print(f"请求 {request_id}，第 {result['attempt']} 轮。将回写这些文件：", file=out)
    for repo in result.get("repos", []):
        print(f"  仓库 {repo['name']}（{repo['path']}）：从 {repo['base_ref']}（{repo['base_commit'][:12]}）新建分支 {result['branch']}，写入文件，不提交。", file=out)
    if any(item["action"] == "delete" for item in result["files"]):
        print("  注意：标着 delete 的文件会被删除。", file=out)
    for item in result["files"]:
        print(f"  {item['action']:9} {item['path']}  (+{item['added']} -{item['removed']})", file=out)
    print(f"完整差异在这个文件里，先在编辑器里打开看：{review}", file=out)
    try:
        approval.ask("确认回写", result["plan_sha256"], "没有批准。什么都没有写。", reader)
    except approval.Refused as error:
        raise CommandError(str(error)) from error
    with store.locked(root, request_id) as locked:
        store.require_open(locked)
        again = make_plan(root, request_id, locked)
        if again["plan_sha256"] != result["plan_sha256"] or locked["promote"].get("plan_sha256") != result["plan_sha256"]:
            raise CommandError("你确认的时候计划变了。让 agent 重新运行 promote --dry-run，再来批准。")
        locked["promote"]["approved_plan_sha256"] = result["plan_sha256"]
        locked["promote"]["approved_at"] = utc_now()
    return {"approved": True, "plan_sha256": result["plan_sha256"], "files": len(result["files"]), "review_file": review, "next": "告诉 agent 可以运行 promote 了。"}


def partial_request(root: Path) -> str:
    """The one open request whose promote stopped halfway. Raises when there is none or several."""
    found = [item["request_id"] for item in ops.list_requests(root, "open")["requests"] if item["promote"] == "partial"]
    if not found:
        raise CommandError("没有中途出错的 promote。用 `request list` 看所有请求。")
    if len(found) > 1:
        raise CommandError("有好几个请求的 promote 中途出错：" + "、".join(found) + "。用 --request 指定一个。")
    return found[0]


def recover(
    root: Path,
    request_id: str = "",
    reader: Optional[Callable[[str], str]] = None,
    interactive: Optional[bool] = None,
    out: Any = None,
) -> Dict[str, Any]:
    """The person puts the repositories back after a promote that stopped halfway. Terminal only, like `approve`.

    Runs the recorded steps (restore the written files, switch back, delete the new branch) one repository at a time.
    When every step is done or not needed, the request goes back to "no promote yet": `--dry-run` and a new approval follow.
    """
    out = out or sys.stdout
    request_id = request_id or partial_request(root)
    try:
        approval.require_person("recover", interactive)
    except approval.Refused as error:
        raise CommandError(str(error)) from error
    data = store.read_request(root, request_id)
    store.require_open(data)
    record = data["promote"]
    if record["state"] != "partial":
        raise CommandError("这个请求的 promote 没有中途出错，不需要恢复。")
    steps = record.get("recovery_steps")
    if steps is None:  # a record written before the steps were kept: only the printed commands exist
        raise CommandError("这个请求的记录里没有可以自动运行的恢复步骤。照 `request show` 里 promote.recovery 的命令，自己逐条运行。")
    print(f"请求 {request_id}：promote 中途出错（出错的仓库 {record.get('repo_failed', '')}：{record.get('error', '')}）。将运行：", file=out)
    for command in record.get("recovery", []) or ["（没有要运行的命令：没有仓库被改动）"]:
        print(f"  {command}", file=out)
    try:
        approval.ask("确认恢复", record["plan_sha256"], "没有确认。什么都没有做。", reader)
    except approval.Refused as error:
        raise CommandError(str(error)) from error
    found = ops.load_targets(root)
    results = promote_target.run_recovery(steps, record["branch"], found.timeout)
    for item in results:
        print(f"  [{item['status']}] {item['command']}" + (f"  {item['message']}" if item["message"] else ""), file=out)
    failed = [item for item in results if item["status"] == "failed"]
    if failed:
        raise CommandError(
            f"{len(failed)} 步没有成功（上面标 [failed] 的）。先按 git 的提示处理（例如文件夹只读、文件被占用），再运行一次 recover：已经做完的步骤会跳过。"
        )
    with store.locked(root, request_id) as locked:
        locked["promote"] = {"state": "none", "recovered_at": utc_now()}
    counts = {status: sum(1 for item in results if item["status"] == status) for status in ("done", "skipped")}
    return {"recovered": True, "request_id": request_id, **counts, "next": "仓库已经恢复。让 agent 重新运行 promote --dry-run，用户再批准。"}


def run(root: Path, request_id: str, dry_run: bool) -> Dict[str, Any]:
    with store.locked(root, request_id) as data:
        store.require_open(data)
        if data["promote"]["state"] == "done":
            raise CommandError("这个请求已经 promote 过了，不再回写第二次。需要再改，用 `request new` 开新请求。")
        partial = data["promote"]["state"] == "partial"
        if partial and not dry_run:
            raise CommandError("上次 promote 中途出错，仓库可能还是半成品。先让用户按恢复命令把仓库恢复成原样（命令在 `request show` 的 promote.recovery 里），再重新 --dry-run、批准。")
        try:
            result = make_plan(root, request_id, data)
        except CommandError as error:
            if partial:
                raise CommandError(f"{error}\n（上次 promote 中途出错。如果仓库还没有恢复，先让用户运行 promote.recovery 里的命令。）") from error
            raise
        if dry_run:
            record = {"state": "dry_run", "plan_sha256": result["plan_sha256"], "at": utc_now()}
            old = data["promote"]
            if old.get("approved_plan_sha256") == result["plan_sha256"]:
                record.update(approved_plan_sha256=old["approved_plan_sha256"], approved_at=old["approved_at"])  # same plan: keep the approval
            data["promote"] = record
            result["approved"] = "approved_plan_sha256" in record
            result["review_file"] = write_review(root, request_id, result, bool(data.get("target_mode")))
            result["next"] = (
                "已经有用户的批准，可以运行 promote（去掉 --dry-run）。"
                if result["approved"]
                else f"告诉用户：完整差异在 [{REVIEW_FILE}]({result['review_file']})（给出这个链接，让用户在编辑器里打开看，不要把差异贴进对话）。"
                "看完后请用户在自己的终端运行：" + approve_command(request_id) + "，输入确认码。用户批准后，再运行 promote（去掉 --dry-run）。"
            )
            return {"dry_run": True, **shown(result)}
        if data["promote"]["state"] != "dry_run" or data["promote"].get("plan_sha256") != result["plan_sha256"]:
            raise CommandError("还没有对应的 --dry-run，或者成果、仓库在 dry-run 之后变了。先重新运行 --dry-run，让用户看过再批准。")
        if data["promote"].get("approved_plan_sha256") != result["plan_sha256"]:
            raise CommandError(
                "用户还没有批准这份计划。请用户在自己的终端运行：" + approve_command(request_id)
                + "，看完计划，按提示输入确认码。你不能自己运行它。用户说批准好了，再运行 promote。"
            )
        if data.get("target_mode"):
            record, failed = promote_target.run(root, data, request_id, result)
            data["promote"] = record  # a `partial` record is saved too: the lock writes it back, the error is raised after
            if not failed:
                result["next"] = (
                    f"已写到各仓库的新分支 {result['branch']}，文件没有提交，成果和补丁备份在 {record['dev']}。"
                    "告诉用户：在每个仓库里检查改动、自己 commit。然后用 `request set-status accepted` 结束请求。"
                )
                return {"dry_run": False, **shown(result)}
            failure = promote_target.partial_message(record)
        else:
            directory = layout.request_dir(root, request_id)
            package = layout.package_dir(directory, data["attempt"], "reviewer")
            for item in result["files"]:
                if item["action"] == "unchanged":
                    continue
                ops.copy_file(package / "candidate" / item["path"], root / item["path"])
            result = shown(result)
            data["promote"] = {
                "state": "done",
                "plan_sha256": result["plan_sha256"],
                "approved_plan_sha256": data["promote"]["approved_plan_sha256"],
                "approved_at": data["promote"]["approved_at"],
                "at": utc_now(),
                "files": [{"path": f["path"], "action": f["action"], "sha256": f["sha256"]} for f in result["files"]],
            }
            result["next"] = "已回写。用 `request set-status accepted` 结束请求。"
            return {"dry_run": False, **result}
    raise CommandError(failure)
