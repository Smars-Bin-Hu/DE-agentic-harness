---
description: '在 .workspace/ 里读写文件的规则'
applyTo: '.workspace/**'
---

# .workspace 的使用规则

目录约定和 gate 的能力边界见 [.workspace/README.md](../../.workspace/README.md)。

- L1、L2：不走 sandbox。其他路径照常写，guardrail 文件除外。
- L2 的任务模式（运行过 `task start`）：只能在任务目录 `current_tasks/<任务>/` 里写。
  - 要回写到目标仓库的成果放 `DEV/<仓库名>/<路径>`。计划写在 `PLAN.md`，用户在终端运行 `task approve-plan` 批准后，才能写 `DEV/`。
  - 不回写的成果（RCA、设计、笔记、一次性脚本）放任务目录根下，不用批准。
  - 步骤见技能 `harness-task-level`。
- 目标仓库里的文件所有 Level 都不能直接改。L2 用 `task fetch` 取到 `DEV/`，改完用 `task promote`；L3 用 `promote`。两者都要用户在终端批准。
- L3：只在当前请求目录 `.workspace/sandbox/requests/<request-id>/` 下写。写到别处会被 hook 拒绝。
  要回写到仓库，用 `promote`：先 `--dry-run`，把计划给用户看，请用户在自己的终端运行 `request approve-promote` 批准，再 `promote`。你不能自己运行 `approve-promote`。
- guardrail 文件所有 Level 都不能改。清单在 [.harness/policies/gate.json](../../.harness/policies/gate.json)。用户在终端开了 admin 模式的会话除外。
- 读取不受限制。skills、指令、知识库都可以读。
- 不要直接写 `request.json`、`handoff.json`、`manifest.json`、`knowledge-brief.md`、`brief-history/`、`promote-plan.diff`，和任务目录里的 `.task/`、`CHANGES.diff`、`PROMOTE-PLAN.diff`。它们由 CLI 生成，hook 会拒绝直接写入。清单见 `gate.json` 的 `cli_owned_paths`。
- 要用这些文件时，用 `<cli>` 的命令：`request`、`brief set`、`attempt new`、`dispatch`、`handoff submit`、`check`、`promote`。`--help` 看用法。`<cli>` 是 `python .harness/engine/cli.py`（Windows）或 `python3 .harness/engine/cli.py`（macOS/Linux）。
- 已经派发的输入包和已经提交的 handoff 是只读的，不要改。
- 创建文件前，父目录要先存在。用终端建：macOS/Linux 用 `mkdir -p`，Windows 用 `mkdir`。
- 写入被拒绝时，照理由里的下一步做。不要用终端命令绕过。
- `current_tasks/<任务>/` 里的 `REQ/`、`REF/` 是人放的材料，只读。`reports/` 由 CLI 写。
- 要用户批准时，给出文件的链接（`plan.md`、`PLAN.md`、`promote-plan.diff`、`PROMOTE-PLAN.diff`），让用户在编辑器里看。不要把全文贴进对话。
- `goals/<id>/` 里的 `GOAL.md`、`TODO.md`、`NOW.md`、`LOG.md` 和 `accept/` 是长任务的记录，用户用 `/generic-goal-driven` 启动后才有。L1、L2 普通模式下可以直接写。L2 任务模式（`task close` 之前）和 L3 请求进行中不能写，要在任务或请求结束后写。流程见技能 `generic-goal-driven`。
