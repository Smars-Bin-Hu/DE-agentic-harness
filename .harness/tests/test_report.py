"""Report (B9-A, M5-3): the Markdown page of a request. Facts only, written when the request is concluded."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict

from support import payload, pre_tool

from test_request import SESSION, RequestCase


class ReportCase(RequestCase):
    def report_file(self, request_id: str) -> Path:
        return self.root / ".workspace" / "reports" / f"{request_id}.md"

    def text(self, request_id: str) -> str:
        return self.report_file(request_id).read_text(encoding="utf-8")

    def conclude(self, request_id: str, status: str, reason: str = "") -> Dict[str, Any]:
        extra = ["--reason", reason] if reason else []
        if status == "accepted" and self.request(request_id)["promote"]["state"] != "done" and self.request(request_id)["attempts"]:
            self.promote_for_real(request_id)  # an accepted request has its result in the repository
        return self.run_cli("request", "set-status", "--request", request_id, "--status", status, *extra)


class ConcludeWritesTheReportTests(ReportCase):
    def test_set_status_writes_the_report_and_says_where(self) -> None:
        request_id = self.passed_request()
        result = self.conclude(request_id, "accepted")
        self.assertEqual(result["report"], f".workspace/reports/{request_id}.md")
        self.assertTrue(self.report_file(request_id).is_file())
        self.assertNotIn("report_error", result)

    def test_an_accepted_request_reads_as_passed_with_both_handoffs(self) -> None:
        request_id = self.passed_request()
        self.conclude(request_id, "accepted")
        text = self.text(request_id)
        self.assertIn("# 请求报告：Add slugify", text)
        self.assertIn("已通过", text)
        self.assertIn("| 1 | passed | passed | - |", text)
        self.assertIn("**builder：passed**", text)
        self.assertIn("**reviewer：passed**", text)
        self.assertIn("evidence/test.log", text)

    def test_a_knowledge_addition_reads_as_a_sentence_not_as_a_dict(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.fill_assignment(request_id, 1, "builder")
        self.dispatch(request_id, "builder")
        self.submit(request_id, "builder", "blocked", "--blocker", "need input", "--kb-addition", "knowledge-base/a.md#部署 :: 先停写再迁移")
        self.run_cli("report", "--request", request_id)
        text = self.text(request_id)
        self.assertIn("- 查到的知识：先停写再迁移（来源：knowledge-base/a.md#部署）", text)
        self.assertNotIn("{'source'", text)

    def test_a_failed_round_then_a_pass_shows_both_rounds_and_the_blocker(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1)
        self.reviewer_round(request_id, 1, "failed")
        self.attempt(request_id)
        self.builder_round(request_id, 2)
        self.reviewer_round(request_id, 2)
        self.conclude(request_id, "accepted")
        text = self.text(request_id)
        self.assertIn("| 1 | passed | failed | - |", text)
        self.assertIn("| 2 | passed | passed | - |", text)
        self.assertIn("问题：slugify keeps spaces", text)
        self.assertIn("### 第 2 轮", text)

    def test_hitl_says_why_with_the_reason_the_round_count_and_the_last_blocker(self) -> None:
        request_id = self.new_request()
        for number in (1, 2):
            self.attempt(request_id)
            self.builder_round(request_id, number)
            self.reviewer_round(request_id, number, "failed")
        refused = self.refused("attempt", "new", "--request", request_id)
        self.assertIn("上限", refused)
        self.conclude(request_id, "hitl", "two rounds failed")
        text = self.text(request_id)
        self.assertIn("## 为什么是 hitl", text)
        self.assertIn("写下的原因：two rounds failed", text)
        self.assertIn("做了 2 轮，上限 2。到了上限。", text)
        self.assertIn("第 2 轮 reviewer 是 failed：slugify keeps spaces", text)

    def test_a_builder_that_is_blocked_shows_in_the_table_and_the_blockers(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        self.builder_round(request_id, 1, "blocked")
        self.conclude(request_id, "hitl", "builder is blocked")
        text = self.text(request_id)
        self.assertIn("| 1 | blocked | 未交 | - |", text)
        self.assertIn("builder 是 blocked：tests do not pass", text)

    def test_an_attempt_past_the_limit_shows_who_agreed(self) -> None:
        request_id = self.new_request()
        for number in (1, 2):
            self.attempt(request_id)
            self.builder_round(request_id, number)
            self.reviewer_round(request_id, number, "failed")
        self.attempt(request_id, approved="the person wants one more try")
        self.conclude(request_id, "abandoned", "gave up")
        self.assertIn("| 3 | 未交 | 未交 | the person wants one more try |", self.text(request_id))

    def test_a_promoted_request_lists_the_files(self) -> None:
        request_id = self.passed_request()
        self.promote_for_real(request_id)
        self.conclude(request_id, "accepted")
        text = self.text(request_id)
        self.assertIn("已回写到仓库", text)
        self.assertIn("- create src/slug.py", text)

    def test_a_request_without_a_round_still_gets_a_report(self) -> None:
        request_id = self.new_request()
        self.conclude(request_id, "abandoned", "changed my mind")
        text = self.text(request_id)
        self.assertIn("还没有开过一轮", text)
        self.assertIn("已放弃", text)

    def test_a_report_that_cannot_be_written_does_not_undo_the_conclusion(self) -> None:
        request_id = self.new_request()
        (self.root / ".workspace" / "reports").parent.mkdir(parents=True, exist_ok=True)
        (self.root / ".workspace" / "reports").write_text("a file where the folder should be", encoding="utf-8")
        result = self.conclude(request_id, "abandoned", "x")
        self.assertIn("report_error", result)
        self.assertEqual(self.request(request_id)["status"], "abandoned")


class ReportCommandTests(ReportCase):
    def test_an_open_request_can_be_reported_and_reads_as_not_concluded(self) -> None:
        request_id = self.new_request()
        self.attempt(request_id)
        result = self.run_cli("report", "--request", request_id)
        self.assertEqual((result["status"], result["report"]), ("open", f".workspace/reports/{request_id}.md"))
        self.assertIn("进行中，还没有收尾", self.text(request_id))

    def test_without_an_id_the_newest_request_is_used(self) -> None:
        self.hook(payload("UserPromptSubmit", "sess-other", prompt="start"))
        self.new_request("zzz older")
        newer = self.new_request("aaa newer", session="sess-other")
        self.assertEqual(self.run_cli("report")["request_id"], newer)

    def test_no_request_is_a_clear_refusal(self) -> None:
        self.assertIn("还没有请求", self.refused("report"))

    def test_a_bad_id_is_refused(self) -> None:
        self.assertIn("不合法", self.refused("report", "--request", "../x"))

    def test_running_it_again_rewrites_the_page(self) -> None:
        request_id = self.passed_request()
        self.run_cli("report", "--request", request_id)
        self.assertNotIn("已通过", self.text(request_id))
        self.conclude(request_id, "accepted")
        self.assertIn("已通过", self.text(request_id))


class LogSectionTests(ReportCase):
    def test_refusals_of_the_session_are_listed_with_who_and_why(self) -> None:
        request_id = self.new_request()
        self.hook(pre_tool(SESSION, "create_file", {"filePath": str(self.root / ".harness/policies/gate.json"), "content": "x"}))
        self.hook(pre_tool(SESSION, "run_in_terminal", {"command": "rm old.txt"}))
        self.conclude(request_id, "abandoned", "x")
        text = self.text(request_id)
        self.assertIn("## hook 日志（会话 sess-main）", text)
        self.assertIn("拒绝（deny） 1", text)
        self.assertIn("要人确认（ask） 1", text)
        self.assertIn("| create_file | deny | rule:gate |", text)
        self.assertIn("| run_in_terminal | ask | human:gate |", text)
        self.assertIn("rm old.txt", text)

    def test_a_clean_session_says_there_were_no_refusals(self) -> None:
        request_id = self.new_request()
        self.hook(pre_tool(SESSION, "read_file", {"filePath": "/w/a.txt"}))
        self.conclude(request_id, "abandoned", "x")
        self.assertIn("没有拒绝和确认记录", self.text(request_id))

    def test_calls_before_the_request_do_not_count(self) -> None:
        self.hook(pre_tool(SESSION, "create_file", {"filePath": str(self.root / ".harness/policies/gate.json"), "content": "x"}))
        path = self.root / ".harness" / "runtime" / "logs" / "vscode" / f"{SESSION}.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            row["at"] = "2000-01-01T00:00:00+00:00"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        request_id = self.new_request()
        self.conclude(request_id, "abandoned", "x")
        text = self.text(request_id)
        self.assertIn("拒绝（deny） 0", text)
        self.assertIn("没有拒绝和确认记录", text)

    def test_a_missing_log_is_said_not_hidden(self) -> None:
        request_id = self.new_request()
        for path in (self.root / ".harness" / "runtime" / "logs").rglob("*.jsonl"):
            path.unlink()
        self.conclude(request_id, "abandoned", "x")
        self.assertIn("没有找到这个会话的日志", self.text(request_id))

    def test_subagent_sessions_of_the_sdk_engine_are_counted_with_the_parent(self) -> None:
        request_id = self.new_request()
        logs = self.root / ".harness" / "runtime" / "logs" / "vscode"
        row = {"at": "2999-01-01T00:00:00+00:00", "event": "PreToolUse", "decision": "deny", "judge": "rule", "by": ["gate"],
               "reason": "no", "tool_name": "Write", "parent_session_id": SESSION, "session_id": "child-1", "surface": "vscode"}
        (logs / "child-1.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.conclude(request_id, "abandoned", "x")
        text = self.text(request_id)
        self.assertIn("子 agent 另有 1 个会话", text)
        self.assertIn("| Write | deny | rule:gate |", text)

    def test_the_report_has_no_tool_arguments_beyond_the_refused_ones(self) -> None:
        request_id = self.new_request()
        self.hook(pre_tool(SESSION, "read_file", {"filePath": str(self.root / "secret" / "customer.sql")}))
        self.conclude(request_id, "abandoned", "x")
        self.assertNotIn("customer", self.text(request_id))

    def test_the_orchestrator_cannot_write_the_report_with_an_edit_tool(self) -> None:
        output = self.hook(pre_tool(SESSION, "create_file", {"filePath": str(self.root / ".workspace/reports/x.md"), "content": "x"}))
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
