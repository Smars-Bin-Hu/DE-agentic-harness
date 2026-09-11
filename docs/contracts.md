# Contract schema

Every agent and skill in this harness gets a sidecar `contract.yaml` describing what
it expects, what it guarantees, and how it's evaluated. The contract is documentation
+ a schema for the eval harness (see `eval/README.md`) to check against — Claude Code
itself does not read or enforce it.

## Where the file lives

- **Skills** already live in their own directory, so the contract nests inside it:
  `.claude/skills/<name>/contract.yaml` (see `.claude/skills/example-skill/contract.yaml`).
- **Agents** are flat `.md` files that Claude Code auto-discovers from
  `.claude/agents/*.md` — turning `<name>/` into a directory would break that
  discovery. So an agent's contract is a sibling file:
  `.claude/agents/<name>.contract.yaml` (see
  `.claude/agents/example-agent.contract.yaml`).

## Fields

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Must match the `name` in the paired `.md` frontmatter. |
| `version` | string (semver) | Bump when behavior, inputs, or outputs change. |
| `owner` | string | Who maintains this agent/skill. Placeholder until real ownership exists. |
| `summary` | string | One paragraph: what it does, when it should be used. |
| `inputs` | list of `{name, type, required, description}` | What the caller must/may provide. |
| `outputs` | `{type, description, schema}` | Shape of the final result. `schema` is an optional pointer to a JSON Schema file for strict validation; `null` while informal. |
| `preconditions` | list of strings | Plain-language assumptions that must hold before invocation. |
| `postconditions` | list of strings | Plain-language guarantees once it completes successfully. |
| `side_effects.allowed` | list of strings | Side effects it's permitted to cause (file writes, network calls, git ops, etc.). |
| `side_effects.forbidden` | list of strings | Explicitly out of bounds — the nearest thing to a guardrail today (see `docs/guardrails.md`). |
| `failure_modes` | list of `{condition, behavior}` | How it should fail and report when something goes wrong. |
| `eval.fixtures_dir` | path | Where this agent/skill's eval cases live (see `eval/README.md`). |
| `eval.rubric_ref` | path | Pointer to the scoring rubric it's judged against. |
| `allowed_tools` *(agents only)* | list of strings | Should mirror the `tools` field in the agent's frontmatter. |

## Adding a new contract

1. Copy `.claude/skills/example-skill/contract.yaml` or
   `.claude/agents/example-agent.contract.yaml` depending on what you're building.
2. Fill in every field — an empty/placeholder field is a sign the contract wasn't
   thought through, not a sign it's optional.
3. Add at least one fixture case under `eval.fixtures_dir` (see `eval/README.md`).
