# DE Agentic Harness

This repo is the **scaffolding for a Claude Code harness**. It exists to test Claude
Code's basic capabilities (agents, skills, MCP tools, hooks) *before* the real Data
Engineering project it will eventually operate on is wired in. Right now there is no
application code — just the harness skeleton.

## Architecture pillars

- **agents** (`.claude/agents/`) — subagent definitions Claude Code can dispatch to
  for focused subtasks.
- **skills** (`.claude/skills/`) — packaged instructions/workflows invoked on demand
  (via `/skill-name` or automatically when relevant).
- **tools** (`.mcp.json`) — external tool integrations via MCP (Model Context
  Protocol) servers.
- **knowledge-base** (`knowledge-base/`) — reference docs / domain context that
  agents and skills can point to.

See `CLAUDE.md` for the full guide given to Claude Code when it operates in this
repository.

## Layout

```
.
├── CLAUDE.md               # guidance for Claude Code in this repo
├── .mcp.json               # MCP server registrations (tools pillar)
├── .claude/
│   ├── settings.json       # permissions + hooks config
│   ├── agents/              # subagent definitions
│   │   └── example-agent.md
│   ├── skills/               # skill packages
│   │   └── example-skill/SKILL.md
│   └── hooks/                # scripts invoked by settings.json hooks
│       └── example-hook.sh
└── knowledge-base/          # reference/context docs (empty for now)
```

## Smoke-testing this skeleton

1. Open this directory in Claude Code.
2. Run `/agents` and confirm `example-agent` is listed.
3. Invoke the example skill and confirm it responds.
4. Start a new session and check that `.claude/hooks.log` picked up a new line
   (proves the `SessionStart` hook fired).
5. `.mcp.json` currently registers no servers (`{"mcpServers": {}}`). To add a real
   one, add an entry under `mcpServers` per the [MCP docs](https://modelcontextprotocol.io/),
   e.g. a `command`/`args` pair for a local server, or a `url` for a remote one.

## Roadmap

Not yet built, but planned once the real Data Engineering project is integrated:
eval harness, fine-grained permission management, observability/tracing, and
guardrails. See `CLAUDE.md` for notes.
