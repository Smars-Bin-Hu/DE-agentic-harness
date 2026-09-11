# Permission management (design notes, not implemented)

## Current state

`.claude/settings.json` has flat, global `permissions.allow` / `permissions.deny`
lists. Every agent and skill in this harness shares the same permission surface.
`.claude/settings.local.json` (gitignored) layers personal overrides on top.

## Where this needs to go

Once the real DE project is integrated and agents start touching real tool access
(databases, cloud consoles, ticket trackers), a single flat allow/deny list won't be
enough to express "this agent may run read-only SQL, that one may also deploy
pipeline configs." The intended direction:

- **Role/task-scoped profiles** — separate permission sets per agent or per class of
  task (e.g. `reviewer` vs. `pipeline-deploy`), rather than one global list.
- Likely implemented as multiple settings files or overlays selected per
  agent/session, building on the same `permissions.allow`/`deny` shape Claude Code
  already reads — not a new mechanism from scratch.
- Should reference each agent's `contract.yaml` (`docs/contracts.md`) — an agent's
  `side_effects.allowed`/`forbidden` is the natural source of truth for what its
  permission profile ought to contain.

Not implemented — this is a placeholder for when real, permission-sensitive tool
integrations exist to design against.
