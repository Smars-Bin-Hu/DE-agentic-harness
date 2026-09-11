# Guardrails (design notes, not implemented)

## Current state

No enforcement beyond Claude Code's own built-in confirmation prompts for risky
Bash/destructive operations. There is no repo-specific gate yet.

## Where this needs to go

Data Engineering work has its own categories of destructive operations that generic
confirmation prompts won't know to flag — e.g. dropping/altering a production schema,
mutating prod data, force-pushing pipeline config that other jobs depend on. Once
real tool integrations exist, the intended direction is:

- Enumerate the DE-specific destructive-operation categories that matter for the
  real project (schema changes, data mutations, deploys, etc.).
- Add a **deny-capable `PreToolUse` hook** — unlike `.claude/hooks/log-event.sh`
  (which only observes and always exits `0`, see `docs/observability.md`), a
  guardrail hook would inspect the tool call and exit non-zero to block it when it
  matches a forbidden category.
- Cross-reference each agent/skill's `contract.yaml` `side_effects.forbidden` list
  (`docs/contracts.md`) so the guardrail enforces what the contract already claims,
  instead of drifting from it.

Not implemented — this is a placeholder for when real, higher-stakes tool access
exists to design enforcement against.
