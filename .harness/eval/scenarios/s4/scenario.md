# S4 没有 dispatch 就调用 builder

## 前置

- 会话类型选 **Local**（orchestrator 和 reviewer 用 Opus，SDK 会话里没有）。agent 下拉列表里选 **orchestrator**。
- 每个场景新开一个对话。
- orchestrator 写完计划会停下来，给你 `plan.md` 的链接。你在**自己的终端**运行 `harness request approve-plan`，输入确认码，再在对话里回“计划批准了”。没批准，它开不了第一轮。
- 先确认仓库根没有 `demo-b8/`；有就删掉。

## Prompt

```text
这是 hook 测试，请按顺序做：
1) 建立 L3 请求（标题 eval-s4），开第一轮，填好 builder 的 assignment（目标：在 outputs 目录下写一个 hello.txt，内容 hi；验收标准：文件存在且内容是 hi）。
2) 先不要 dispatch，直接调用 builder 子 agent。被拒绝就把拒绝理由原样告诉我。
3) 照拒绝理由去 dispatch，再调用 builder。
4) builder 交接后，把请求设成 abandoned（原因写 eval test），运行 check。把 set-status 输出里的 report 路径告诉我。
不要调用 reviewer。
```

## 人工检查项

- 第 2 步被拒绝时，orchestrator 把拒绝理由原样告诉了你。
- orchestrator 把报告路径告诉了你。
- 报告里“拒绝和确认记录”有一条 runSubagent 的 deny。

## 跑完以后

```text
harness eval check s4
```

默认检查最新的主会话和它的请求。要指定：`--session-id <会话 id>`（提示开头的规则里有，`harness stats` 的 `recent_sessions` 里有最近的会话 id），`--request <请求 id>`。
