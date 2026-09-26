# Skill Content Template

### Body Content

The body contains detailed instructions that Copilot loads AFTER the skill is activated. Recommended sections:

| Section | Purpose |
| --- | --- |
| `# Title` | Brief overview of what this skill enables |
| `## When to Use This Skill` | List of scenarios (reinforces description triggers) |
| `## Prerequisites` | Required tools, dependencies, environment setup (if applicable) |
| `## Step-by-Step Workflows` | Numbered steps for repeatable procedures (build, deploy, setup) |
| `## Gotchas` | Proactive warnings about non-obvious behavior ("never do X because Y") |
| `## Troubleshooting` | Reactive fixes for known issues ("if you see X, try Y") |

Not every skill needs every section. Skip `## Prerequisites` if there are no external dependencies. Skip `## Step-by-Step Workflows` if the skill is purely advisory. Include `## Gotchas` whenever the skill involves external tools, APIs, or platform-specific behavior.

For content quality principles (what to include and what to leave out), see Writing High-Impact Skills below.
