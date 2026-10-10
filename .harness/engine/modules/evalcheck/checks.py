"""Run the checks of one scenario against one finished run. Reads only; every answer is yes or no with a reason."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import config
from core.logs import read_lines, session_files
from core.paths import REQUESTS_DIR

CLI = Path(__file__).resolve().parents[2] / "cli.py"


def check_result(name: str, ok: bool, detail: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


# --- which run ------------------------------------------------------------------------------------


def newest_session(root: Path, surface: str) -> Optional[Tuple[str, str]]:
    """The newest session that is a main session (no parent). A subagent's own session is never the run."""
    for found_surface, path in reversed(list(session_files(root))):
        if surface and found_surface != surface:
            continue
        rows = read_lines(path)
        if rows and not any(row.get("parent_session_id") for row in rows):
            return found_surface, path.stem
    return None


def session_rows(root: Path, surface: str, session_id: str) -> List[Dict[str, Any]]:
    """The calls of the session and of the sessions of its subagents (SDK engine), in time order."""
    rows: List[Dict[str, Any]] = []
    for found_surface, path in session_files(root):
        if found_surface != surface:
            continue
        own = read_lines(path)
        if path.stem == session_id or (own and own[0].get("parent_session_id") == session_id):
            rows.extend(own)
    return sorted(rows, key=lambda row: row.get("at", ""))


def find_request(root: Path, session_id: str, request_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    base = root / REQUESTS_DIR
    if request_id:
        path = base / request_id / "request.json"
        return (request_id, json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else None
    best: Optional[Tuple[str, Dict[str, Any]]] = None
    for path in base.glob("*/request.json") if base.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if data.get("session_id") == session_id and (best is None or data.get("created_at", "") > best[1].get("created_at", "")):
            best = (path.parent.name, data)
    return best


# --- matching rows --------------------------------------------------------------------------------


def row_matches(row: Dict[str, Any], match: Dict[str, Any]) -> bool:
    for key, wanted in match.items():
        if key == "by":
            if wanted not in (row.get("by") or []):
                return False
        elif key == "reason_contains":
            if wanted not in (row.get("reason") or ""):
                return False
        elif key == "target_contains":
            target = row.get("target") or {}
            # Windows paths hold "\" and tool calls can give either kind: compare with "/" on both sides.
            wanted_text = wanted.replace("\\", "/")
            if not any(wanted_text in text.replace("\\", "/") for text in list(target.get("paths", [])) + [target.get("command", "")]):
                return False
        elif row.get(key) != wanted:
            return False
    return True


def describe(match: Dict[str, Any]) -> str:
    return "、".join(f"{key}={value}" for key, value in match.items()) or "任何行"


def check_calls(rows: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        count = sum(1 for row in rows if row_matches(row, item["match"]))
        if "exactly" in item:
            low = high = item["exactly"]
        else:
            high = item.get("max")
            low = item.get("min", 0 if high is not None and "min" not in item else 1)
        ok = count >= low and (high is None or count <= high)
        wanted = f"恰好 {low}" if low == high else f"{low} 到 {high}" if high is not None and low else f"最多 {high}" if high is not None else f"至少 {low}"
        results.append(check_result(item["name"], ok, f"匹配 {describe(item['match'])} 的有 {count} 行，要求{wanted}。"))
    return results


def check_order(rows: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        position, missing = 0, None
        for step in item["steps"]:
            while position < len(rows) and not row_matches(rows[position], step):
                position += 1
            if position >= len(rows):
                missing = step
                break
            position += 1
        ok = missing is None
        results.append(check_result(item["name"], ok, "顺序对。" if ok else f"找不到按顺序出现的这一步：{describe(missing or {})}。"))
    return results


# --- the request ----------------------------------------------------------------------------------


def run_check(root: Path, request_id: str, require_conclusion: bool) -> Tuple[bool, str]:
    command = [sys.executable, str(CLI), "check", "--request", request_id] + (["--require-conclusion"] if require_conclusion else [])
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "HARNESS_ROOT": str(root)}, check=False)
    try:
        answer = json.loads(completed.stdout)
    except ValueError:
        return False, (completed.stderr or completed.stdout).strip()[:200]
    return bool(answer.get("ok")), "；".join(answer.get("problems", []))


def check_request(root: Path, request_id: str, data: Dict[str, Any], wanted: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = []
    attempts = data.get("attempts", [])
    for key, value in wanted.items():
        name = f"请求：{key}"
        if key == "status":
            results.append(check_result(name, data["status"] == value, f"状态是 {data['status']}，要求 {value}。"))
        elif key == "attempts":
            results.append(check_result(name, data["attempt"] == value, f"轮数是 {data['attempt']}，要求 {value}。"))
        elif key == "max_attempts_reached":
            limit = config.load_policy(root, "orchestration")["max_attempts"]
            reached = data["attempt"] >= limit
            results.append(check_result(name, reached == value, f"轮数 {data['attempt']}，上限 {limit}。"))
        elif key == "handoffs":
            for number, roles in value.items():
                index = int(number) - 1
                recorded = attempts[index]["handoffs"] if 0 <= index < len(attempts) else {}
                for role, status in roles.items():
                    results.append(check_result(f"请求：第 {number} 轮 {role} 的交接", recorded.get(role) == status, f"是 {recorded.get(role, '未交')}，要求 {status}。"))
        elif key == "human_approved":
            approved = any(item.get("human_approved") for item in attempts)
            results.append(check_result(name, approved == value, "有轮次用了 --human-approved。" if approved else "没有轮次用 --human-approved。"))
        elif key == "pending_dispatch":
            results.append(check_result(name, len(data.get("pending_dispatch", [])) == value, f"待派发记录有 {len(data.get('pending_dispatch', []))} 条，要求 {value}。"))
        elif key == "promote":
            state = data.get("promote", {}).get("state")
            results.append(check_result(name, state == value, f"回写状态是 {state}，要求 {value}。"))
        elif key == "check":
            ok, detail = run_check(root, request_id, bool(value.get("require_conclusion")))
            results.append(check_result("请求：check" + (" --require-conclusion" if value.get("require_conclusion") else ""), ok, detail or "请求目录自洽。"))
        elif key == "report":
            exists = (root / ".workspace" / "reports" / f"{request_id}.md").is_file()
            results.append(check_result(name, exists == value, "报告存在。" if exists else "没有报告。"))
    return results


# --- files and json -------------------------------------------------------------------------------


def check_files(root: Path, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        exists = (root / item["path"]).exists()
        results.append(check_result(f"文件：{item['path']}", exists == item["exists"], "存在。" if exists else "不存在。"))
    return results


def dig(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def check_json(root: Path, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for item in items:
        name = f"JSON：{item['file']} 的 {item['path']}"
        try:
            value = dig(json.loads((root / item["file"]).read_text(encoding="utf-8-sig")), item["path"])
        except (OSError, ValueError) as error:
            results.append(check_result(name, False, f"读不了：{error}"))
            continue
        if "equals" in item:
            results.append(check_result(name, value == item["equals"], f"值是 {value!r}，要求等于 {item['equals']!r}。"))
        else:
            results.append(check_result(name, value != item["not_equals"], f"值是 {value!r}，要求不等于 {item['not_equals']!r}。"))
    return results


# --- one scenario ---------------------------------------------------------------------------------


def run(root: Path, scenario: Dict[str, Any], surface: str, session_id: str, request_id: str) -> Dict[str, Any]:
    expect = scenario["expect"]
    if not session_id:
        picked = newest_session(root, surface)
        if picked is None:
            raise ValueError("没有找到会话日志。先在 Copilot 里跑一遍场景，或用 --session-id 指定。")
        surface, session_id = picked
    rows = session_rows(root, surface, session_id)
    if not rows:
        raise ValueError(f"会话 `{session_id}` 在 {surface} 下没有日志。检查 id（`harness stats` 能列出日志在不在），或日志是否被清理。")
    results = check_calls(rows, expect.get("calls", [])) + check_order(rows, expect.get("order", []))
    found_request: Optional[str] = None
    if "request" in expect:
        found = find_request(root, session_id, request_id)
        if found is None:
            results.append(check_result("请求", False, "没有找到这个会话的请求。用 --request 指定，或确认会话 id。"))
        else:
            found_request = found[0]
            results += check_request(root, found[0], found[1], expect["request"])
    results += check_files(root, expect.get("files", [])) + check_json(root, expect.get("json", []))
    failed = [item for item in results if not item["ok"]]
    return {
        "scenario": scenario["id"],
        "passed": not failed,
        "failed": len(failed),
        "checks": results,
        "session": {"surface": surface, "session_id": session_id, "calls": len(rows)},
        "request": found_request,
        "manual_checks": scenario["manual"],
        "note": "通过只代表确定性检查全部满足。人工检查项要你自己看。",
    }
