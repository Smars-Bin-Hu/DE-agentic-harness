---
name: task-level-policy
description: Classify and manage the active Task Level for every task in this harness. Use when starting, escalating, downgrading, replacing, or completing a task, or when work risks exceeding the active autonomy budget. Do not use this skill to change filesystem, network, environment, or production permissions.
---

# Task Level Policy

Task Level controls autonomy, not permissions. The policy engine starts every new
task at Level 1 and hooks enforce only observable V1 behavior. Read
`references/task-level-policy.md` before classifying a non-trivial task.

## Workflow

1. Read the active Task Level from the SessionStart hook context. It includes the
   runtime name and session id. If the context is unavailable, proceed at Level 1
   and do not assume that additional autonomy is allowed.
2. Respect an explicit user request for a level. Otherwise use the lowest
   sufficient level: deterministic and narrow work is L1; bounded multi-file
   engineering is L2; cross-subsystem, parallel, or orchestrated work is L3.
3. Before work exceeds the active policy, transition it with the shared engine:

   ```text
   python3 .harness/task-policy/task_policy.py set-level \
     --runtime copilot --session-id <session-id> --level <1|2|3> \
     --reason "<concrete scope reason>"
   ```

4. Explain an upgrade or downgrade to the user. Do not silently use forbidden
   autonomy, especially subagents in L1 or L2.
5. If the user replaces an unfinished task, begin a fresh L1 task and preserve
   the previous task as replaced:

   ```text
   python3 .harness/task-policy/task_policy.py begin \
     --runtime copilot --session-id <session-id> --replace \
     --reason "User replaced the active task."
   ```

6. Before a final completion response, mark the task complete:

   ```text
   python3 .harness/task-policy/task_policy.py complete \
     --runtime copilot --session-id <session-id> \
     --reason "<what was completed>"
   ```

## Classification Rules

- **Level 1 — Deterministic:** a clear answer, a narrow single-file edit, or an
  established SOP with no architecture investigation. Act directly after only
  the required read and validation.
- **Level 2 — Standard engineering:** a bounded multi-file change, a new skill,
  targeted investigation, tests, or a short implementation plan. Explore only
  the relevant area and keep the plan short.
- **Level 3 — Complex / orchestrated:** multiple subsystems or workflows, broad
  dependency analysis, complex RCA, or genuinely independent work that benefits
  from parallel agents. Make a plan before delegating.

## Runtime Behavior

The hooks create a default L1 task when a user submits a prompt, preserve an
active task across follow-up prompts, count visible tool/search activity, and
block subagent creation where the policy forbids it. A hook does not change the
runtime permission model, and hooks may be unavailable in GitHub Copilot IDE
agent mode. In that mode this skill and `AGENTS.md` remain the source of truth.

The V1 counters are soft budgets except for subagent caps. Do not try to evade a
warning by resetting counters; assess scope and transition levels when justified.
