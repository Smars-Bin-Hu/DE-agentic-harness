# S1 一轮通过，然后 promote

## 前置

- 会话类型选 **Local**（orchestrator 和 reviewer 用 Opus，SDK 会话里没有）。agent 下拉列表里选 **orchestrator**。
- 每个场景新开一个对话。
- orchestrator 写完计划会停下来，给你 `plan.md` 的链接。你在**自己的终端**运行 `harness request approve-plan`，输入确认码，再在对话里回“计划批准了”。没批准，它开不了第一轮。
- 先确认仓库根没有 `demo-b8/`；有就删掉。

## Prompt

```text
请完成这个 L3 请求：在 demo-b8/ 下写 slugify(s)（转小写，把空格换成连字符，放在 demo-b8/slug.py）和 3 个 unittest 测试（demo-b8/test_slug.py）。
验收标准：在 demo-b8/ 目录下运行 python -m unittest（macOS/Linux 用 python3），全部通过。
走完整流程（builder、reviewer）。两个额外要求（流程测试）：
a) 调用 builder 和 reviewer 时，调用消息里只写“请开始”，不要写任何路径或请求 id。
b) 填 assignment 时，让 builder 和 reviewer 在 handoff 的 summary 第一行写上自己的模型名（例如 model: xxx）。
reviewer 通过后，运行 promote --dry-run，把计划给我看，然后停下来等我批准。我批准以后会告诉你，你再 promote 并结束请求。
```

orchestrator 给你计划后，你在**自己的终端**运行它给你的命令（`harness request approve-promote`），输入确认码。然后在**同一个对话**里回：

```text
我批准了。
```

## 人工检查项

- builder 和 reviewer 的调用消息只有“请开始”，它们仍然第一步读了自己的 assignment（hook 注入有效）。
- handoff 的 summary 第一行是各自的模型名，两个系列不同。
- 等你批准时，orchestrator 先运行了 request wait（`request list` 里 waiting_for 有内容）。
- 测完删掉 `demo-b8/`。

## 跑完以后

```text
harness eval check s1
```

默认检查最新的主会话和它的请求。要指定：`--session-id <会话 id>`（提示开头的规则里有，`harness stats` 的 `recent_sessions` 里有最近的会话 id），`--request <请求 id>`。
