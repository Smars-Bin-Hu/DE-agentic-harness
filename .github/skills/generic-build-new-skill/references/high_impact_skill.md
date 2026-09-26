# Writing High-Impact Skills





### Writing Style

- Use imperative mood: "Run", "Create", "Configure" (not "You should run")
- Be specific and actionable
- Include exact commands with parameters
- Show expected outputs where helpful
- Keep sections focused and scannable
### Focus on What Copilot Doesn't Know

Do not include information Copilot already knows from its training data — standard language syntax, common library usage, or well-documented API behavior. Every line in a skill should teach something Copilot would otherwise get wrong or miss entirely. If the information is on the first page of official docs, leave it out. Focus on internal conventions, non-obvious defaults, version-specific quirks, and domain-specific workflows that change Copilot's behavior.

### Context Budget Awareness

All skill descriptions share a limited portion of the available context window during discovery. Your description competes with every other installed skill for Copilot's attention. Keep descriptions concise and keyword-dense — aim for the shortest text that still communicates WHAT, WHEN, and relevant KEYWORDS. Verbose descriptions don't just waste your own budget; they reduce visibility for every other skill in the system.

### Gotchas Are Your Highest-Signal Content

The `## Gotchas` section is consistently the most valuable part of any skill — proactive warnings that prevent mistakes before they happen. This is distinct from `## Troubleshooting`, which provides reactive fixes after something goes wrong. Treat gotchas as a living section: every time Copilot produces a wrong result, add a gotcha. Bold the key constraint, then explain why (e.g., "**Never** call `X()` without checking `Y` first — the SDK throws an unrecoverable error").

### Prefer Flexible Guidelines Over Rigid Steps

Use numbered steps only for concrete, repeatable procedures (build, deploy, environment setup) where the sequence genuinely matters. For open-ended tasks (debugging, refactoring, code review), provide decision criteria and reference information instead — Copilot needs flexibility to adapt to the user's specific situation.

```markdown
# ❌ Too rigid
1. Open the file at src/api/handlers.ts
2. Find the function named processOrder
3. Add a try-catch block around lines 45-60

# ✅ Flexible
When fixing error handling in API handlers:
- Ensure all database operations have proper error handling
- Use the project's ErrorHandler utility (see ./references/error-handling.md)
- Log errors with enough context to debug in production
```

### Use Progressive Disclosure for Large Skills

If your `SKILL.md`exceeds ~200 lines, consider splitting detailed content into subdirectories. This reduces context consumption — Copilot loads only the core instructions initially and pulls reference material on demand.

```markdown
## Reference Files

- `references/api.md` — complete function signatures and return types
- `references/error-codes.md` — every error code this service can return
- `scripts/validate.sh` — run this after making changes to verify correctness

Read these files as needed for your current task. Do not read them all upfront.
```

## Common Patterns

### Parameter Table Pattern

Document parameters clearly:

```markdown
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--input` | Yes | - | Input file or URL to process |
| `--action` | Yes | - | Action to perform |
| `--verbose` | No | `false` | Enable verbose output |
```

### Workflow Execution Pattern

When executing multi-step workflows, create a TODO list where each step references the relevant documentation:

```markdown
## TODO
- [ ] Step 1: Configure environment - see workflow-setup.md
- [ ] Step 2: Build project - see workflow-setup.md
- [ ] Step 3: Deploy to staging - see workflow-deployment.md
- [ ] Step 4: Run validation - see workflow-deployment.md
- [ ] Step 5: Deploy to production - see workflow-deployment.md
```

This ensures traceability and allows resuming workflows if interrupted.

## Validation Checklist

Before publishing a skill:

- [ ]  `SKILL.md` has valid frontmatter with `name` and `description`
- [ ]  `name` is lowercase with hyphens, ≤64 characters
- [ ]  `description` clearly states **WHAT** it does, **WHEN** to use it, and relevant **KEYWORDS**
- [ ]  `description` is concise and keyword-dense (respects context budget)
- [ ]  Body focuses on information Copilot wouldn't know from training data
- [ ]  Body includes when to use, prerequisites (if applicable), and core instructions
- [ ]  `## Gotchas` section present if skill involves non-obvious behavior, API quirks, or common traps
- [ ]  SKILL.md body under 500 lines (consider splitting into `references/` at ~200 lines; 500 is the hard maximum)
- [ ]  Large workflows (>5 steps) split into `references/` folder with clear links from SKILL.md
- [ ]  Scripts include help documentation and error handling
- [ ]  Relative paths used for all resource references
- [ ]  No hardcoded credentials or secrets