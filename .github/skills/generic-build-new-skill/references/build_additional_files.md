# Bundling Additional Resources

Skills can include additional files that Copilot accesses on-demand:

### Supported Resource Types

| Folder | Purpose | Loaded into Context? | Example Files |
| --- | --- | --- | --- |
| `scripts/` | Executable automation that performs specific operations | When executed | `helper.py`, `validate.sh`, `build.ts` |
| `references/` | Documentation the AI agent reads to inform decisions | Yes, when referenced | `api_reference.md`, `schema.md`, `workflow_guide.md` |
| `assets/` | **Static files used AS-IS** in output (not modified by the AI agent) | No | `logo.png`, `brand-template.pptx`, `custom-font.ttf` |
| `templates/` | **Starter code/scaffolds that the AI agent MODIFIES** and builds upon | Yes, when referenced | `viewer.html` (insert algorithm), `hello-world/` (extend) |

### Directory Structure Example

```
.agents/skills/my-skill/
├── SKILL.md              # Required: Main instructions
├── LICENSE.txt           # Recommended: License terms (Apache 2.0 typical)
├── scripts/              # Optional: Executable automation
│   ├── helper.py         # Python script
│   └── helper.ps1        # PowerShell script
├── references/           # Optional: Documentation loaded into context
│   ├── api_reference.md
│   ├── workflow-setup.md     # Detailed workflow (>5 steps)
│   └── workflow-deployment.md
├── assets/               # Optional: Static files used AS-IS in output
│   ├── baseline.png      # Reference image for comparison
│   └── report-template.html
└── templates/            # Optional: Starter code the AI agent modifies
    ├── scaffold.py       # Code scaffold the AI agent customizes
    └── config.template   # Config template the AI agent fills in
```

> **LICENSE.txt**: When creating a skill, download the Apache 2.0 license text from https://www.apache.org/licenses/LICENSE-2.0.txt and save as `LICENSE.txt`. Update the copyright year and owner in the appendix section.
> 

### Assets vs Templates: Key Distinction

**Assets** are static resources **consumed unchanged** in the output:

- A `logo.png` that gets embedded into a generated document
- A `report-template.html` copied as output format
- A `custom-font.ttf` applied to text rendering

**Templates** are starter code/scaffolds that **the AI agent actively modifies**:

- A `scaffold.py` where the AI agent inserts logic
- A `config.template` where the AI agent fills in values based on user requirements
- A `hello-world/` project directory that the AI agent extends with new features

**Rule of thumb**: If the AI agent reads and builds upon the file content → `templates/`. If the file is used as-is in output → `assets/`.

Script Requirements

When including scripts, prefer cross-platform languages:

| Language | Use Case |
| --- | --- |
| Python | Complex automation, data processing |
| pwsh | PowerShell Core scripting |
| Node.js | JavaScript-based tooling |
| Bash/Shell | Simple automation tasks |

Best practices:

- Include help/usage documentation (`-help` flag)
- Handle errors gracefully with clear messages
- Avoid storing credentials or secrets
- Use relative paths where possible

### When to Bundle Scripts

Include scripts in your skill when:

- The same code would be rewritten repeatedly by the agent
- Deterministic reliability is critical (e.g., file manipulation, API calls)
- Complex logic benefits from being pre-tested rather than generated each time
- The operation has a self-contained purpose that can evolve independently
- Testability matters — scripts can be unit tested and validated
- Predictable behavior is preferred over dynamic generation

Scripts enable evolution: even simple operations benefit from being implemented as scripts when they may grow in complexity, need consistent behavior across invocations, or require future extensibility.

### Security Considerations

- Scripts rely on existing credential helpers (no credential storage)
- Include `-force` flags only for destructive operations
- Warn users before irreversible actions
- Document any network operations or external calls
