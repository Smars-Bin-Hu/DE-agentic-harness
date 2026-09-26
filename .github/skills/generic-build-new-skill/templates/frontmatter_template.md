### Frontmatter (Required)

```yaml
---
name: generic-webdev-testapp
description: 'Toolkit for testing local web applications using Playwright. Use when asked to verify frontend functionality, debug UI behavior, capture browser screenshots, check for visual regressions, or view browser console logs. Supports Chrome, Firefox, and WebKit browsers.'
license: Complete terms in LICENSE.txt
type: unit
specificTo: generic
---
```

| Field | Required | Constraints |
| --- | --- | --- |
| `name` | Yes | Lowercase, hyphens for spaces, max 64 characters (e.g., `generic-webapp-testing`) |
| `description` | Yes | 10–1024 characters, clear capabilities AND use cases, wrapped in single quotes |
| `license` | No | Reference to LICENSE.txt (e.g., `Complete terms in LICENSE.txt`) or SPDX identifier |
| `type` | Yes | (e.g. `Type:Unit` Skill 是完成一个确定性的单元化任务，有确定的输入、输出，一般是一个工作流的 Step 或者是常被使用的工具；`Type:workflow`当Skill是一个复杂任务流的编排 |
|  `specificTo` | Yes | e.g. `<domain-name>` or `generic` 跨Domain可用的Skill 或者 面向某一个业务领域的Skill |

### Description Best Practices

**CRITICAL**: The `description` field is the PRIMARY mechanism for automatic skill discovery. Copilot reads ONLY the `name` and `description` to decide whether to load a skill. If your description is vague, the skill will never be activated.

**What to include in description:**

1. **WHAT** the skill does (capabilities)
2. **WHEN** to use it (specific triggers, scenarios, file types, or user requests)
3. **Keywords** that users might mention in their prompts

**Good description:**

```yaml
description: 'Toolkit for testing local web applications using Playwright. Use when asked to verify frontend functionality, debug UI behavior, capture browser screenshots, check for visual regressions, or view browser console logs. Supports Chrome, Firefox, and WebKit browsers.'
```