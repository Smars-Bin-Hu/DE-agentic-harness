---
description: 'Guidelines for creating high-quality Agent Skills for GitHub Copilot'
applyTo: '../skills/**/SKILL.md'
---

# Progressive Loading Architecture

| Level | What Loads | When |
| --- | --- | --- |
| 1. Discovery | `name` and `description` only | Always (lightweight metadata) |
| 2. Instructions | Full `SKILL.md` body | When request matches description |
| 3. Resources | Scripts, examples, docs | Only when Copilot
 

# Generic Skill vs Domain Skill
- Generic Skill: 命名为`generic-<skill-name>`跨Domain可用的Skill
- Domain Skill: 命名为 `domain-<domain name>-<skill-name>*` 面向某一个业务领域的Skill


# Unit Type vs Workflow Orchestration Tyle

- Unit Type: Skill 是完成一个确定性的单元化任务，有确定的输入、输出，一般是一个工作流的 Step 或者是常被使用的工具。

- Workflow Orchestration Type: 当Skill是一个复杂任务流的编排

- Directory Structure Example
# Skill Files Structure
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
