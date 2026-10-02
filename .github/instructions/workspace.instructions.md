---
description: '在 .workspace/ 里读写文件的规则'
applyTo: '.workspace/**'
---

# .workspace 的使用规则

目录约定和 gate 的能力边界见 [.workspace/README.md](../../.workspace/README.md)。

- L1、L2：不走 sandbox。其他路径照常写，guardrail 文件除外。
- L3：只在当前请求目录 `.workspace/sandbox/requests/<request-id>/` 下写。写到别处会被 hook 拒绝。
  要回写到仓库，用 `promote`，要人确认。
- guardrail 文件所有 Level 都不能改。清单在 [.harness/policies/gate.json](../../.harness/policies/gate.json)。
- 读取不受限制。skills、指令、知识库都可以读。
- 不要写 `request.json`、`handoff.json` 和 `manifest.json`。它们由 CLI 生成。
- 写入被拒绝时，照理由里的下一步做。不要用终端命令绕过。
- `current_tasks/` 是人放材料的地方，只读。`reports/` 由 CLI 写。
