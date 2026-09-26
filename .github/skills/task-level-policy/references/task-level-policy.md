# Task Level Reference

## Scope

Task Level is task-scoped execution policy. It controls autonomy, planning,
exploration, delegation, and soft execution budgets. It never grants runtime,
filesystem, network, environment, or production permissions.

Every new task begins at Level 1. An active task retains its level across follow-up
prompts until it is explicitly completed or replaced. A completed task resets its
default level to Level 1 for the next user request.

## V1 Levels

| Level | Use when | Planning | Exploration | Subagents | V1 soft budget |
| --- | --- | --- | --- | --- | --- |
| 1 | Deterministic, narrow, or SOP-backed work | Disabled | Minimal | Blocked | 2 searches / 15 tools |
| 2 | Bounded engineering across related files | Recommended | Limited | Blocked | 8 searches / 40 tools |
| 3 | Cross-system, complex RCA, or useful parallelism | Required | Broad | Up to 4 | 25 searches / 120 tools |

Subagent limits are hard. Search and observed-tool budgets produce a one-time
warning at 80% of budget or above; they are not a permission gate.

## Escalation and Downgrade

Escalate L1 to L2 when narrow work needs related-file discovery, a short plan, or
multiple implementation choices. Escalate L2 to L3 only for cross-subsystem
dependencies, complex RCA, or independent work that materially benefits from
delegation. Downgrade once broad investigation has reduced the remaining work to a
smaller, focused task.

Each transition requires a concrete reason and preserves the existing counters.
The state keeps the transition history and the latest completed/replaced tasks for
the current session.

## Observable V1 Metrics

`observed_tool_calls` counts locally hook-visible tool calls. `repository_searches`
counts Grep/Glob and recognized local `rg`, `grep`, `git grep`, or `find` commands.
Hosted tools that bypass the local hook path are not counted. File reads/writes,
retries, iterations, and dynamic reasoning changes are intentionally deferred.

## Compatibility

GitHub Copilot CLI and cloud agent use `.github/hooks/task-level-policy.json`,
which calls the engine under `.harness/task-policy/`. GitHub Copilot IDE agent mode loads shared instructions
and skills but does not provide this hook enforcement layer.
