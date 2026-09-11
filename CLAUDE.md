# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This is a **harness skeleton**, not an application. It will eventually drive multiple
SDLC tasks (code review, pipeline authoring, testing, docs, etc.) for a separate Data
Engineering project, which is not yet integrated. Until that project lands, there is:

- No build, lint, or test command — there is no application code to build/lint/test.
- No CI.

Do not invent build/test commands or assume application code exists elsewhere in this
directory — verify with `ls`/`find` before assuming a command applies here.

## Architecture

The harness is organized around four pillars:

1. **Agents** — `.claude/agents/*.md`. Each file is a subagent definition (YAML
   frontmatter with `name`, `description`, optional `tools`/`model`, followed by the
   subagent's system instructions). Add new agents by copying
   `.claude/agents/example-agent.md` and adjusting the frontmatter and instructions.

2. **Skills** — `.claude/skills/<skill-name>/SKILL.md`. Each skill is a directory with
   a `SKILL.md` (frontmatter: `name`, `description` — the description is what Claude
   uses to decide when the skill is relevant). Add new skills by copying
   `.claude/skills/example-skill/`.

3. **Tools** — `.mcp.json` at the repo root. This is where external tool integrations
   (databases, ticket trackers, cloud APIs, etc.) get registered as MCP servers. It is
   currently an empty stub (`{"mcpServers": {}}`); populate it as real integrations are
   needed rather than pre-registering speculative servers.

4. **Knowledge base** — `knowledge-base/`. Plain reference docs (domain glossaries,
   architecture notes, data contracts, etc.) that agents/skills can be pointed to for
   context. Currently empty; will be populated once the real DE project is integrated.

## Contracts

Every agent and skill has a sidecar `contract.yaml` (inputs, outputs, pre/post
conditions, allowed/forbidden side effects, failure modes) — see
`docs/contracts.md` for the schema and where the file lives for each of the two
(skills nest it in their directory; agents get a `<name>.contract.yaml` sibling of
`<name>.md`). Any new agent or skill should ship a contract alongside it.

## Eval

`eval/README.md` defines the fixture format (`fixtures/case-NNN/{input.json,
expected.json}`) and scoring rubric that agent/skill contracts point to via
`eval.fixtures_dir`. This is conventions-only for now — there is no runnable scorer
yet, since there's no real content to score. Add fixtures alongside any new
contract; the runner is future work.

## Permissions and hooks

`.claude/settings.json` holds the project's permission rules (`permissions.allow` /
`permissions.deny`) and hook wiring (`hooks`). Hooks currently wired:

- `SessionStart` → `.claude/hooks/example-hook.sh` (the original "hooks work" demo,
  logs to `.claude/hooks.log`) and `.claude/hooks/log-event.sh SessionStart`.
- `PreToolUse` / `PostToolUse` (matcher `*`), `SubagentStop`, `Stop` →
  `.claude/hooks/log-event.sh <EventName>`.

`log-event.sh` is the observability logger — see below. Use the same
`.claude/hooks/*.sh` + `settings.json` wiring pattern for future hooks (e.g. a
pre-commit lint gate).

`.claude/settings.local.json` (gitignored) is where personal/local permission
overrides should go — never commit machine-specific permissions to
`.claude/settings.json`.

## Observability

`docs/observability.md` describes the implemented design: `log-event.sh` wraps
whatever Claude Code sends a hook on stdin as `{ts, event_type, payload}` and
appends it to `.claude/logs/events.jsonl` (gitignored); logger failures go to
`.claude/logs/hook-errors.log` instead of blocking the hook. Read that doc before
changing the log schema or adding new hook-driven events.

## Roadmap (not yet implemented)

These are known future needs for the eventual Data Engineering harness — design
notes exist so they aren't forgotten, but nothing is enforced yet:

- **Permission management** — `docs/permissions.md`. Beyond the basic allow/deny
  list in `settings.json`, likely role- or task-scoped permission profiles once real
  tool access (databases, prod systems) is involved.
- **Guardrails** — `docs/guardrails.md`. Input/output validation and deny-capable
  hooks appropriate to a Data Engineering context (e.g. preventing destructive
  schema/data operations), once real tool integrations exist to design against.
