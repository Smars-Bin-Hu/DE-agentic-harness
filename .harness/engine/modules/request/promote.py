"""promote: the one way a result gets back into the repository (design: "受控回写").

Only the files the reviewer saw (to-reviewer/candidate/) are copied, and only when the last reviewer handoff is
`passed`. Candidate paths are repository-relative paths. `--dry-run` shows the plan. The real run needs the person's approval of that same plan, given with
`request approve-promote`: it works only in a terminal the person types in (stdin and stdout are a TTY) and asks them to
type a code from the plan. A tool-call dialog cannot be the guard, because "Allow in this Session" switches it off.
The gate also denies an agent that tries to run `approve-promote`.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import config, repo_paths
from core.paths import utc_now

from . import layout, ops, store
from .layout import CommandError

DIFF_PREVIEW_LINES = 40
ALWAYS_REFUSED = (".git/**", ".workspace/**")


def refused_patterns(root: Path) -> List[Tuple[str, Any]]:
    """Targets promote must never write: the gate's guardrail and CLI-owned files, plus `.git` and `.workspace`."""
    try:
        gate = config.load_policy(root, "gate")
        names = list(gate["guardrail_paths"]) + list(gate.get("extra_guardrail_paths", [])) + list(gate.get("cli_owned_paths", []))
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
        entry: Dict[str, Any] = {"path": target_name, "sha256": item["sha256"]}
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


def approve_command(request_id: str) -> str:
    return f"python3 .harness/engine/cli.py request approve-promote --request {request_id}"


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
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        raise CommandError("approve-promote 只能由用户在自己的终端里手动运行，要打字确认。agent 不能运行它，管道和脚本也不行。")
    data = store.read_request(root, request_id)
    store.require_open(data)
    if data["promote"]["state"] != "dry_run":
        raise CommandError("还没有 --dry-run 的计划，或者已经 promote 过。先让 agent 运行 promote --dry-run。")
    result = plan(root, request_id, data)
    if result["plan_sha256"] != data["promote"]["plan_sha256"]:
        raise CommandError("成果或仓库在 dry-run 之后变了。让 agent 重新运行 promote --dry-run，再来批准。")
    print(f"请求 {request_id}，第 {result['attempt']} 轮。将回写这些文件：", file=out)
    for item in result["files"]:
        print(f"  {item['action']:9} {item['path']}  (+{item['added']} -{item['removed']})", file=out)
        for line in item["diff"][:12]:
            print(f"      {line}", file=out)
    code = code_of(result["plan_sha256"])
    answer = (reader or input)(f"确认回写，输入 {code}（其他任何输入都是取消）：").strip()
    if answer != code:
        raise CommandError("没有批准。什么都没有写。")
    with store.locked(root, request_id) as locked:
        store.require_open(locked)
        again = plan(root, request_id, locked)
        if again["plan_sha256"] != result["plan_sha256"] or locked["promote"].get("plan_sha256") != result["plan_sha256"]:
            raise CommandError("你确认的时候计划变了。让 agent 重新运行 promote --dry-run，再来批准。")
        locked["promote"]["approved_plan_sha256"] = result["plan_sha256"]
        locked["promote"]["approved_at"] = utc_now()
    return {"approved": True, "plan_sha256": result["plan_sha256"], "files": len(result["files"]), "next": "告诉 agent 可以运行 promote 了。"}


def run(root: Path, request_id: str, dry_run: bool) -> Dict[str, Any]:
    with store.locked(root, request_id) as data:
        store.require_open(data)
        if data["promote"]["state"] == "done":
            raise CommandError("这个请求已经 promote 过了，不再回写第二次。需要再改，用 `request new` 开新请求。")
        result = plan(root, request_id, data)
        if dry_run:
            record = {"state": "dry_run", "plan_sha256": result["plan_sha256"], "at": utc_now()}
            old = data["promote"]
            if old.get("approved_plan_sha256") == result["plan_sha256"]:
                record.update(approved_plan_sha256=old["approved_plan_sha256"], approved_at=old["approved_at"])  # same plan: keep the approval
            data["promote"] = record
            result["approved"] = "approved_plan_sha256" in record
            result["next"] = (
                "已经有用户的批准，可以运行 promote（去掉 --dry-run）。"
                if result["approved"]
                else "把这份计划给用户看，请用户在自己的终端运行：" + approve_command(request_id) + "。用户批准后，再运行 promote（去掉 --dry-run）。"
            )
            return {"dry_run": True, **result}
        if data["promote"]["state"] != "dry_run" or data["promote"].get("plan_sha256") != result["plan_sha256"]:
            raise CommandError("还没有对应的 --dry-run，或者成果、仓库在 dry-run 之后变了。先重新运行 --dry-run，让用户看过再批准。")
        if data["promote"].get("approved_plan_sha256") != result["plan_sha256"]:
            raise CommandError(
                "用户还没有批准这份计划。请用户在自己的终端运行：" + approve_command(request_id)
                + "，看完计划，按提示输入确认码。你不能自己运行它。用户说批准好了，再运行 promote。"
            )
        directory = layout.request_dir(root, request_id)
        package = layout.package_dir(directory, data["attempt"], "reviewer")
        for item in result["files"]:
            if item["action"] == "unchanged":
                continue
            ops.copy_file(package / "candidate" / item["path"], root / item["path"])
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
