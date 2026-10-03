# S2 reviewer 判 failed，第二轮通过

## 前置

- 会话类型选 **Local**（orchestrator 和 reviewer 用 Opus，SDK 会话里没有）。agent 下拉列表里选 **orchestrator**。
- 每个场景新开一个对话。
- 先确认仓库根没有 `demo-b8/`；有就删掉。

## Prompt

```text
请完成这个 L3 请求：在 demo-b8/ 下写 slugify(s)（demo-b8/slug.py）和 3 个 unittest 测试（demo-b8/test_slug.py）。
流程测试，第一轮请这样写 assignment：builder 的 assignment 只写“转小写，把空格换成连字符”，不要提首尾空格；reviewer 的验收标准要多一条：slugify("  A b ") 必须返回 "a-b"。
如果 reviewer 判 failed，开第二轮，把这条补进 builder 的 assignment（用 attempt new，不用 human-approved）。第二轮通过后，运行 promote --dry-run，把计划给我看，然后停下。不要 promote。最后把请求设成 abandoned（原因写 eval test）。
```

## 人工检查项

- 第二轮的 builder assignment 里有 reviewer 提出的问题。
- orchestrator 没有用 `--human-approved`。
- 测完不需要删 `demo-b8/`（没有 promote）；如果有，删掉。

## 跑完以后

```text
python .harness/engine/cli.py eval check s2
```

默认检查最新的主会话和它的请求。要指定：`--session-id <会话 id>`（提示开头的规则里有，`cli.py stats` 的 `recent_sessions` 里有最近的会话 id），`--request <请求 id>`。
