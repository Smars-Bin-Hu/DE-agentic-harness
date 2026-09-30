---
description: 'Guidelines for creating high-quality Agent Skills for GitHub Copilot'
applyTo: '.github/skills/**/SKILL.md'
---

# Progressive Loading Architecture

| Level | What Loads | When |
| --- | --- | --- |
| 1. Discovery | `name` and `description` only | Always (lightweight metadata) |
| 2. Instructions | Full `SKILL.md` body | When request matches description |
| 3. Resources | Scripts, examples, docs | Only when Copilot
 

# Skill 名称前缀

Skill 的目录名和 `name` 字段必须一致，并且用下面三种前缀之一。没有前缀的只有第三方 Skill，保留原名。

- `harness-<module>`：harness 模块的语义面。和 `.harness/engine/modules/<module>/` 一一对应，模块名里的下划线写成连字符（`task_level` → `harness-task-level`）。上游维护。
- `generic-<skill-name>`：跨领域通用的 Skill。上游维护。
- `domain-<domain name>-<skill-name>`：面向某一个业务领域的 Skill。企业维护，上游不建。


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
