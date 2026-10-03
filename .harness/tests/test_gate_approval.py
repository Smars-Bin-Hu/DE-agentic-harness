"""git commands and `approve-command` (B10-A5, M4-10): a read passes, a write waits for a person, some are never approved."""

from __future__ import annotations

import json
import unittest
from typing import Optional

from support import HarnessTestCase, pre_tool

from modules.gate import approvals, commands, gitcmd

NONE, APPROVE, NEVER = gitcmd.NONE, gitcmd.APPROVE, gitcmd.NEVER


class ClassifyTests(unittest.TestCase):
    def check(self, kind: str, *commands_: str) -> None:
        for command in commands_:
            with self.subTest(command):
                self.assertEqual(gitcmd.classify(command).kind, kind, gitcmd.classify(command))

    def test_reads_pass(self) -> None:
        self.check(
            NONE, "git status", "git -C /x/y log --oneline", "git diff HEAD~1 -- a.sql", "git show HEAD:a.sql", "git branch", "git branch -a -v",
            "git tag", "git tag -l 'v*'", "git stash list", "git stash show -p", "git config --get user.name", "git config --list", "git remote -v",
            "git worktree list", "git rev-parse --show-toplevel", "git ls-files", "git cat-file -p HEAD", "git log --format=%s | head", "git version",
            "git", "git --version", "git reflog", "git blame a.sql", "git grep -n select", "rg 'git push' docs", 'echo "git commit"', "gh issue list",
            "git -C repo --no-pager diff", "ls -la && git status",
        )

    def test_writes_need_approval(self) -> None:
        self.check(
            APPROVE, "git add .", 'git commit -m "fix; thing"', "git commit --amend", "git checkout -b feature/x", "git switch -c a", "git switch main",
            "git restore a.sql", "git reset HEAD a.sql", "git stash", "git stash drop", "git merge x", "git rebase -i main", "git cherry-pick abc",
            "git branch newone", "git branch -d old", "git tag v1", "git config user.name x", "git remote add o url", "git worktree add ../x",
            "git fetch", "git pull", "git clone x", "git init", "git mv a b", "git rm a", "git apply p.diff", "git gc", "git ci", "git $CMD",
            "git -c core.pager=sh log", "git diff --output=x.txt", "GIT_SSH_COMMAND=x git fetch", "git submodule update",
        )

    def test_never_approved(self) -> None:
        self.check(
            NEVER, "git push", "git push origin main", "git -C repo push", "git push --force", "git push -f", "git push --force-with-lease",
            "git clean -fd", "git clean -n", "git reset --hard", "git reset --hard HEAD~1", "git branch -D x", "git branch -d x --force",
            "git checkout -f main", "git checkout --force main", "git switch -f main", "git switch --discard-changes main", "git add -f a",
            "git rm -f a", "git fetch --force", "git worktree remove -f x", "git reflog expire --all", "git reflog delete HEAD@{1}",
            "git filter-branch --all", "git update-ref -d refs/heads/x", "git gc --prune=now", "git prune", "gh pr create", "gh pr merge 3",
        )

    def test_force_letter_means_force_only_where_git_says_so(self) -> None:
        self.check(APPROVE, "git tag -F msg.txt v1", "git config -f file k v", "git commit -F msg.txt", "git commit -m fix")

    def test_how_it_is_written_does_not_hide_a_git_command(self) -> None:
        self.check(
            APPROVE, "cd repo && git commit -m x", "echo hi | git apply", "& git commit -m x", "& 'C:\\Program Files\\Git\\cmd\\git.exe' commit -m x",
            "git.exe add .", "/usr/bin/git add .", "sudo git commit", "env FOO=1 git commit", "timeout 5 git commit", "echo $(git commit -m x)",
            "bash -c 'git add . && git commit -m x'", "python3 -c \"import subprocess; subprocess.run(['git','commit'])\"",
        )
        self.check(NEVER, "bash -c \"git add . && git push\"", "cd x; git status; git push", "git status && git push", "echo x | git push", "git status\ngit clean -fd")

    def test_never_wins_over_a_write_in_the_same_line(self) -> None:
        verdict = gitcmd.classify("git add . && git commit -m x && git push")
        self.assertEqual(verdict.kind, NEVER)
        self.assertIn("push", verdict.why)
        self.assertEqual(len(verdict.commands), 3)

    def test_collapse(self) -> None:
        self.assertEqual(gitcmd.collapse("git   commit\t-m  'a  b'\n"), "git commit -m 'a b'")


class StoreTests(HarnessTestCase):
    def test_a_command_waits_then_is_approved_once(self) -> None:
        code = approvals.request(self.root, "vscode", "s1", "git  commit -m x", 10, now=1000)
        self.assertEqual(len(code), 6)
        self.assertEqual(approvals.request(self.root, "vscode", "s1", "git commit -m x", 10, now=1010), code)  # same command, same code
        self.assertFalse(approvals.consume(self.root, "s1", "git commit -m x", 10, now=1020))  # not approved yet
        self.assertIsNotNone(approvals.approve(self.root, code.lower(), 10, now=1030))
        self.assertTrue(approvals.consume(self.root, "s1", "git   commit -m x", 10, now=1040))  # white space folded
        self.assertFalse(approvals.consume(self.root, "s1", "git commit -m x", 10, now=1050))  # used up

    def test_the_approval_is_for_one_command_in_one_session(self) -> None:
        code = approvals.request(self.root, "vscode", "s1", "git commit -m x", 10, now=1000)
        approvals.approve(self.root, code, 10, now=1001)
        self.assertFalse(approvals.consume(self.root, "s2", "git commit -m x", 10, now=1002))
        self.assertFalse(approvals.consume(self.root, "s1", "git commit -m y", 10, now=1002))
        self.assertTrue(approvals.consume(self.root, "s1", "git commit -m x", 10, now=1003))

    def test_it_runs_out(self) -> None:
        code = approvals.request(self.root, "vscode", "s1", "git add .", 10, now=1000)
        self.assertEqual(approvals.pending(self.root, 10, now=1000 + 599), approvals.pending(self.root, 10, now=1000))
        self.assertIsNone(approvals.approve(self.root, code, 10, now=1000 + 601))
        code = approvals.request(self.root, "vscode", "s1", "git add .", 10, now=2000)
        approvals.approve(self.root, code, 10, now=2001)
        self.assertFalse(approvals.consume(self.root, "s1", "git add .", 10, now=2001 + 601))

    def test_a_wrong_code_approves_nothing(self) -> None:
        approvals.request(self.root, "vscode", "s1", "git add .", 10, now=1000)
        self.assertIsNone(approvals.approve(self.root, "ZZZZZZ", 10, now=1001))
        self.assertIsNone(approvals.approve(self.root, "", 10, now=1001))

    def test_a_damaged_file_approves_nothing_and_does_not_crash(self) -> None:
        approvals.path(self.root).parent.mkdir(parents=True, exist_ok=True)
        approvals.path(self.root).write_text("{ not json", encoding="utf-8")
        self.assertFalse(approvals.consume(self.root, "s1", "git add .", 10))
        self.assertEqual(approvals.pending(self.root, 10), [])
        self.assertEqual(len(approvals.request(self.root, "vscode", "s1", "git add .", 10)), 6)

    def test_the_file_stays_small(self) -> None:
        for number in range(80):
            approvals.request(self.root, "vscode", f"s{number}", "git add .", 10, now=1000 + number)
        self.assertLessEqual(len(json.loads(approvals.path(self.root).read_text(encoding="utf-8"))["entries"]), approvals.MAX_ENTRIES)


class GateGitCommandTests(HarnessTestCase):
    session = "git-cmd"

    def setUp(self) -> None:
        super().setUp()
        self.base = str(self.root.resolve())
        self.configure(True)

    def configure(self, on: bool) -> None:
        file = self.root / ".harness" / "policies" / "target.override.json"
        if on:
            file.write_text(json.dumps({"repos": {"x": {"path": str(self.root)}}, "repos_root": ""}), encoding="utf-8")
            (self.root / ".git").mkdir(exist_ok=True)
        elif file.exists():
            file.unlink()

    def term(self, command: str, session: Optional[str] = None) -> dict:
        data = pre_tool(session or self.session, "run_in_terminal", {"command": command, "explanation": "t", "isBackground": False})
        data["cwd"] = self.base
        return self.hook(data)

    def decision(self, output: dict) -> str:
        return output.get("hookSpecificOutput", {}).get("permissionDecision", "")

    def reason(self, output: dict) -> str:
        return output["hookSpecificOutput"]["permissionDecisionReason"]

    def approve(self, code: str) -> dict:
        return commands.approve(self.root, reader=lambda _prompt: code, interactive=True, out=_Sink())

    def pending_code(self) -> str:
        return approvals.pending(self.root, 10)[-1]["code"]

    def test_reads_pass_and_nothing_is_recorded(self) -> None:
        for command in ("git status", "git log --oneline", "git -C /x diff", "git branch -a"):
            self.assertEqual(self.decision(self.term(command)), "", command)
        self.assertEqual(approvals.pending(self.root, 10), [])

    def test_a_write_is_refused_with_the_command_and_a_code_then_runs_once_after_approval(self) -> None:
        output = self.term('git  commit -m "add column"')
        self.assertEqual(self.decision(output), "deny")
        code = self.pending_code()
        for text in (code, 'git commit -m "add column"', "approve-command", "10 分钟"):
            self.assertIn(text, self.reason(output))
        self.assertEqual(self.approve(code)["approved"], True)
        self.assertEqual(self.term('git commit  -m "add column"'), {})  # white space may differ
        again = self.term('git commit -m "add column"')
        self.assertEqual(self.decision(again), "deny")  # used up
        self.assertNotEqual(self.pending_code(), code)

    def test_the_same_command_in_another_session_or_with_other_words_is_refused(self) -> None:
        self.term("git add .")
        self.approve(self.pending_code())
        self.assertEqual(self.decision(self.term("git add .", session="other")), "deny")
        self.assertEqual(self.decision(self.term("git add src")), "deny")
        self.assertEqual(self.term("git add ."), {})

    def test_a_wrong_code_approves_nothing(self) -> None:
        self.term("git add .")
        with self.assertRaises(commands.CommandError):
            self.approve("NOPE00")
        self.assertEqual(self.decision(self.term("git add .")), "deny")

    def test_never_approved_commands_have_no_code_and_no_pending_entry(self) -> None:
        for command in ("git push origin main", "git reset --hard", "git clean -fd", "git branch -D x", "git add -f a", "gh pr create", "git add . && git push"):
            output = self.term(command)
            self.assertEqual(self.decision(output), "deny", command)
            self.assertIn("永远不能批准", self.reason(output))
            self.assertNotIn("approve-command", self.reason(output))
        self.assertEqual(approvals.pending(self.root, 10), [])

    def test_the_whole_compound_command_is_what_gets_approved(self) -> None:
        self.term("git add . && git commit -m x")
        self.approve(self.pending_code())
        self.assertEqual(self.decision(self.term("git add .")), "deny")
        self.assertEqual(self.term("git add . && git commit -m x"), {})

    def test_an_expired_approval_is_refused(self) -> None:
        self.term("git add .")
        code = self.pending_code()
        approvals.approve(self.root, code, 10, now=1.0)  # approved long ago
        self.assertEqual(self.decision(self.term("git add .")), "deny")

    def test_approve_command_is_for_a_person_at_a_terminal(self) -> None:
        self.term("git add .")
        with self.assertRaises(commands.CommandError):
            commands.approve(self.root, reader=lambda _p: self.pending_code(), interactive=False, out=_Sink())
        completed = self.cli("approve-command")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("终端", completed.stderr)
        self.assertEqual(self.decision(self.term("git add .")), "deny")

    def test_nothing_waiting_is_said_clearly(self) -> None:
        with self.assertRaises(commands.CommandError) as caught:
            commands.approve(self.root, reader=lambda _p: "x", interactive=True, out=_Sink())
        self.assertIn("没有等待批准", str(caught.exception))

    def test_an_agent_cannot_run_approve_command(self) -> None:
        for command in ("python3 .harness/engine/cli.py approve-command", "python .harness\\engine\\cli.py approve-command", "py .harness/engine/cli.py approve-command"):
            output = self.term(command)
            self.assertEqual(self.decision(output), "deny", command)
            self.assertIn("approve-command", self.reason(output))

    def test_the_approvals_file_is_a_guardrail(self) -> None:
        data = pre_tool(self.session, "create_file", {"filePath": f"{self.base}/.harness/runtime/git-approvals.json", "content": "{}"})
        data["cwd"] = self.base
        self.assertEqual(self.decision(self.hook(data)), "deny")

    def test_without_target_repositories_git_is_left_alone(self) -> None:
        self.configure(False)
        self.assertEqual(self.term("git commit -m x"), {})
        self.assertEqual(self.decision(self.term("git push")), "ask")  # the old rule of gate.json

    def test_a_broken_target_policy_leaves_git_alone_and_does_not_crash(self) -> None:
        (self.root / ".harness" / "policies" / "target.override.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual(self.term("git commit -m x"), {})

    def test_other_gate_denials_still_come_first(self) -> None:
        output = self.term("git add .harness/policies/gate.json && echo x > .harness/policies/gate.json")
        self.assertIn("guardrail", self.reason(output))
        self.assertEqual(approvals.pending(self.root, 10), [])


class _Sink:
    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
