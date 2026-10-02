---
description: '编写和修改 GitHub Copilot 自定义 agent（.agent.md）的规则'
applyTo: '.github/agents/**/*.agent.md'
---

# agent 的基础规则

## 什么时候可以新增 agent

先用别的办法：指令文件、Skill、hook。只有下面三件事至少有一件不能共用时，才新增 agent：

- 工具范围不同（例如不能给编辑工具）。
- 模型不同（例如固定用便宜的模型）。
- 需要独立的上下文，不能看到调用方的推理。

新增前先回答：它防止什么失败？为什么现有的默认 agent 做不到？

## 谁能直接选

- 用户直接选的 agent 只有两个：默认 agent 和 orchestrator。
- 其他 agent 都只当子 agent 用，写 `user-invocable: false`。
  这个字段只让它不出现在下拉列表，**拦不住被当子 agent 调用**。能不能调用，由 hook 按 Level 判断。
- 不写 `disable-model-invocation: true`，同样拦不住调用。

## 编写要求

- 文件名和 `name` 字段一致。
- `tools` 只写需要的工具集。只读的 agent 不给 `edit`。
- 子 agent 写 `agents: []`，不让它再调子 agent。
- `model` 写显示名，可以写回退列表。名字以公司 Copilot 里看到的为准。
- 正文只写输入、做法、不要做的事、输出格式。输出格式要让 hook 能读：例如 verifier 的第一行是 `VERDICT: PASS` 或 `VERDICT: FAIL`。
- 正文里不写预算数字。数字只在 `.harness/policies/*.json`。

## 现有的 agent

| agent | 用途 | 谁能调用 |
| --- | --- | --- |
| verifier | L2 交付前复核，不改文件。默认关闭，用户写 `[verify]` 才开 | 默认 agent（hook 只在开启时放行） |
