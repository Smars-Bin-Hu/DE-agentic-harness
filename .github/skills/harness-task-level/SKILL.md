---
name: harness-task-level
description: 说明本 harness 的 Task Level（L1、L2、L3）。用户提到 Level、/l1、/l2、[L1]、[L2]，工作量可能超出当前 Level，或被 hook 因预算和子 agent 规则拒绝时使用。不要用它改文件、网络、环境或生产权限。
---

# Task Level

Task Level 是用户为会话选的工作模式。它控制工作方式和探索量，不控制权限。
默认是 L1。只有用户能切换，你只能建议。

## 你要做的

1. 每条用户提示开头，hook 会注入当前 Level 和预算规则。按它做。读不到时，按 L1 工作。
2. 不要自己切换 Level，也不要运行 `level set`。hook 会拒绝这个命令。
3. 发现任务超出当前 Level，或比当前 Level 简单时，停下来告诉用户具体原因，建议用户切换。
   用户在提示开头写 `/l1`、`[L1]`、`/l2` 或 `[L2]` 即可切换。
4. 被 hook 拒绝后，照拒绝理由里的下一步做：
   - 搜索预算用完：根据已读内容直接完成。信息不够就停下来，建议用户用 `/l2` 重发。
   - 子 agent 被拒：自己完成，或建议用户切换 Level。
5. 不要绕开预算。不要用终端命令代替被拒绝的搜索，也不要改 state 文件。

## 三个 Level

- **L1，确定任务**：目标、修改点和验证方式都清楚。不写计划，只读必要的内容，直接动手。不用子 agent。
- **L2，标准工程任务**：要看几个相关文件、写短计划。只探索相关区域。子 agent 只允许 verifier。
- **L3，复杂或编排任务**：跨子系统、复杂 RCA、需要独立验证。由用户切到 orchestrator 进入，不能用标记进入。

具体数字（搜索次数、工具调用次数、子 agent 次数）只在 `.harness/policies/task-levels.json`。
更多说明见 [references/task-level.md](references/task-level.md)。
