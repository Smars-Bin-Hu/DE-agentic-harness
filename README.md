# DE Agentic Harness

This repo is the **scaffolding for a Claude Code harness**. It exists to test Claude
Code's basic capabilities (agents, skills, MCP tools, hooks) *before* the real Data
Engineering project it will eventually operate on is wired in. Right now there is no
application code — just the harness skeleton.

## Architecture pillars

- **agents** (`.claude/agents/`) — subagent definitions Claude Code can dispatch to
  for focused subtasks, each with a sidecar `<name>.contract.yaml`.
- **skills** (`.claude/skills/`) — packaged instructions/workflows invoked on demand
  (via `/skill-name` or automatically when relevant), each with a `contract.yaml`.
- **tools** (`.mcp.json`) — external tool integrations via MCP (Model Context
  Protocol) servers.
- **knowledge-base** (`knowledge-base/`) — reference docs / domain context that
  agents and skills can point to.

Two more things every agent/skill plugs into:

- **contracts** (`docs/contracts.md`) — the schema every `contract.yaml` follows.
- **eval** (`eval/README.md`) — fixture format + scoring rubric a contract's
  `eval.fixtures_dir` points at (conventions only for now, no runner yet).

And one cross-cutting mechanism already wired up:

- **observability** (`docs/observability.md`) — hooks log structured JSON events to
  `.claude/logs/events.jsonl`.

See `CLAUDE.md` for the full guide given to Claude Code when it operates in this
repository.

## Layout

```
.
├── CLAUDE.md               # guidance for Claude Code in this repo
├── .mcp.json               # MCP server registrations (tools pillar)
├── docs/
│   ├── contracts.md         # contract.yaml schema
│   ├── observability.md      # logging design (implemented)
│   ├── permissions.md        # permission profiles (design notes only)
│   └── guardrails.md         # guardrails (design notes only)
├── eval/
│   └── README.md             # fixture format + scoring rubric (conventions only)
├── .claude/
│   ├── settings.json        # permissions + hooks config
│   ├── agents/
│   │   ├── example-agent.md
│   │   ├── example-agent.contract.yaml
│   │   └── example-agent.fixtures/case-001/{input,expected}.json
│   ├── skills/
│   │   └── example-skill/
│   │       ├── SKILL.md
│   │       ├── contract.yaml
│   │       └── fixtures/case-001/{input,expected}.json
│   ├── hooks/
│   │   ├── example-hook.sh   # original SessionStart demo
│   │   └── log-event.sh      # observability logger, wired to several hook events
│   └── logs/                 # events.jsonl / hook-errors.log (gitignored, created at runtime)
└── knowledge-base/          # reference/context docs (empty for now)
```

## Smoke-testing this skeleton

1. Open this directory in Claude Code.
2. Run `/agents` and confirm `example-agent` is listed.
3. Invoke the example skill and confirm it responds.
4. Start a new session and check that `.claude/hooks.log` picked up a new line
   (proves the `SessionStart` hook fired).
5. After doing anything in that session (a tool call, a subagent, ending the
   session), run `tail .claude/logs/events.jsonl` and confirm structured events
   landed there too.
6. Confirm `.claude/skills/example-skill/contract.yaml` and
   `.claude/agents/example-agent.contract.yaml` exist and each has a matching
   `fixtures/case-001/` pair.
7. `.mcp.json` currently registers no servers (`{"mcpServers": {}}`). To add a real
   one, add an entry under `mcpServers` per the [MCP docs](https://modelcontextprotocol.io/),
   e.g. a `command`/`args` pair for a local server, or a `url` for a remote one.

## Roadmap

Design notes exist but nothing is enforced yet: eval runner (`eval/README.md`),
permission profiles (`docs/permissions.md`), guardrails (`docs/guardrails.md`) — all
waiting on the real Data Engineering project to integrate.
