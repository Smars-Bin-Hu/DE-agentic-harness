---
description: '在 .workspace/ 里读写文件的规则'
applyTo: '.workspace/**'
---

# .workspace 的使用规则

目录约定和 gate 的能力边界见 [.workspace/README.md](../../.workspace/README.md)。

- L1、L2：不走 sandbox。其他路径照常写，guardrail 文件除外。
- L3：只在当前请求目录 `.workspace/sandbox/requests/<request-id>/` 下写。写到别处会被 hook 拒绝。
  要回写到仓库，用 `promote`：先 `--dry-run`，把计划给用户看，请用户在自己的终端运行 `request approve-promote` 批准，再 `promote`。你不能自己运行 `approve-promote`。
- guardrail 文件所有 Level 都不能改。清单在 [.harness/policies/gate.json](../../.harness/policies/gate.json)。
- 读取不受限制。skills、指令、知识库都可以读。
- 不要直接写 `request.json`、`handoff.json`、`manifest.json`、`knowledge-brief.md` 和 `brief-history/`。它们由 CLI 生成，hook 会拒绝直接写入。清单见 `gate.json` 的 `cli_owned_paths`。
- 要用这些文件时，用 `<cli>` 的命令：`request`、`brief set`、`attempt new`、`dispatch`、`handoff submit`、`check`、`promote`。`--help` 看用法。`<cli>` 是 `python .harness/engine/cli.py`（Windows）或 `python3 .harness/engine/cli.py`（macOS/Linux）。
- 已经派发的输入包和已经提交的 handoff 是只读的，不要改。
- 创建文件前，父目录要先存在。用终端建：macOS/Linux 用 `mkdir -p`，Windows 用 `mkdir`。
- 写入被拒绝时，照理由里的下一步做。不要用终端命令绕过。
- `current_tasks/` 是人放材料的地方，只读。`reports/` 由 CLI 写。
