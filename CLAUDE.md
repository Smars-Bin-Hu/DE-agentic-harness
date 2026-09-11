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

## Permissions and hooks

`.claude/settings.json` holds the project's permission rules (`permissions.allow` /
`permissions.deny`) and hook wiring (`hooks`). There is currently one example hook
(`SessionStart` → `.claude/hooks/example-hook.sh`) that appends a timestamped line to
`.claude/hooks.log`, demonstrating that the hooks mechanism works end-to-end. Use this
as the pattern for adding real hooks (e.g. a pre-commit lint gate, a PostToolUse audit
log) later.

`.claude/settings.local.json` (gitignored) is where personal/local permission
overrides should go — never commit machine-specific permissions to
`.claude/settings.json`.

## Roadmap (not yet implemented)

These are known future needs for the eventual Data Engineering harness, called out
here so they aren't forgotten, but intentionally not scaffolded yet (no point building
empty structure before the real requirements are known):

- **Eval** — a harness for scoring agent/skill outputs against known-good SDLC task
  outcomes.
- **Permission management** — beyond the basic allow/deny list in `settings.json`,
  likely role- or task-scoped permission profiles once real tool access (databases,
  prod systems) is involved.
- **Observability** — tracing/logging of agent runs beyond the simple hook log, for
  debugging and auditing multi-agent task execution.
- **Guardrails** — input/output validation and safety checks appropriate to a Data
  Engineering context (e.g. preventing destructive schema/data operations).
