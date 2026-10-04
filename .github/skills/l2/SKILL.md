---
name: l2
description: '切到 L2（标准工程任务）：先写短计划，再完成。用户输入 /l2 时使用，由用户手动调用。'
argument-hint: '任务描述'
disable-model-invocation: true
type: unit
specificTo: harness-task-level
---

[L2]

当前 Level 是 L2。先写一份短计划，再动手。只探索相关区域。
用户指定了 `.workspace/current_tasks/<任务>` 并要你产出或修改文件时，走任务模式（见技能 `harness-task-level` 的“L2 的任务模式”）：先 `task start`，写 `PLAN.md`，等用户批准，再在 `DEV/` 下写。
复核按本条提示开头的规则：用户没写 `[verify]` 就不调用子 agent。
任务超出 L2 的范围时，停下来告诉用户原因，建议用户切换。

Level 的规则和被拒绝后怎么办，见技能 `harness-task-level`。
