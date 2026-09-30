---
name: harness-task-level
description: 管理本 harness 的 Task Level。开始、升级、降级、替换或完成任务时使用，也用于工作量可能超出当前 Level 预算时。不要用它改文件、网络、环境或生产权限。
---

# Task Level

Task Level 控制自主程度，不控制权限。每个新任务从 Level 1 开始。
hook 只拦截能观察到的行为。给非平凡任务分级前，先读 `references/task-level.md`。

## 流程

1. 从 SessionStart 或 UserPromptSubmit 的 hook 上下文读取 session id 和当前 Level。
   读不到时，按 Level 1 工作，不要假设有更多自主权。
2. 用户明确指定 Level 时，照做。否则用最低够用的 Level：
   确定的小改动是 L1；有边界的多文件工程是 L2；跨子系统、并行或需要编排的是 L3。
3. 工作量超出当前 Level 之前，先切换。Windows 上把 `python3` 换成 `python`：

   ```text
   python3 .harness/engine/cli.py level set --session-id <session-id> --level <1|2|3> --reason "<具体原因>"
   ```

4. 升级或降级都要告诉用户。L1、L2 不要偷偷使用子 agent。
5. 用户换了任务目标，就开一个新的 L1 任务，并把旧任务记为 replaced：

   ```text
   python3 .harness/engine/cli.py level begin --session-id <session-id> --replace --reason "用户更换了任务。"
   ```

6. 给出最终完成答复之前，把任务标记为完成：

   ```text
   python3 .harness/engine/cli.py level complete --session-id <session-id> --reason "<完成了什么>"
   ```

## 分级规则

- **Level 1，确定任务**：答案明确、单文件的小改动、已有 SOP。只做必要的读取和验证，直接动手。
- **Level 2，标准工程任务**：有边界的多文件修改、新建 skill、定向调查、测试、短计划。只探索相关区域，计划要短。
- **Level 3，复杂或编排任务**：多个子系统或流程、大范围依赖分析、复杂 RCA、确实独立的并行工作。先写计划，再委派。

## hook 做什么

- 用户发提示时，没有进行中的任务就建一个 L1 任务；有就保留，跨后续提示延续。
- 统计可见的工具调用和搜索。
- 当前 Level 不允许子 agent，或子 agent 次数用完时，拒绝创建。

搜索和工具次数是软预算：到 80% 时提醒一次，不拒绝。不要通过重置计数器绕开提醒。
范围真的变了，就切换 Level。
