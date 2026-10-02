---
name: l1
description: '切到 L1（确定任务）：不写计划，直接完成。用户输入 /l1 时使用，由用户手动调用。'
argument-hint: '任务描述'
disable-model-invocation: true
type: unit
specificTo: harness-task-level
---

[L1]

当前 Level 是 L1。直接完成任务：不写计划，只读必要的内容，不用子 agent。
信息不够，或任务比预想的大，就停下来告诉用户原因，建议用户用 /l2 重发。

Level 的规则和被拒绝后怎么办，见技能 `harness-task-level`。
