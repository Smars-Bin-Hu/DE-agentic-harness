# S3 两轮 reviewer 都 failed，到上限，进入 HITL

## 前置

- 会话类型选 **Local**（orchestrator 和 reviewer 用 Opus，SDK 会话里没有）。agent 下拉列表里选 **orchestrator**。
- 每个场景新开一个对话。
- 先确认仓库根没有 `demo-b8/`；有就删掉。

## Prompt

```text
流程测试：请求标题 eval-s3。builder 的 assignment 只写：在 demo-b8/slug.py 写 slugify(s)（转小写，把空格换成 -）。reviewer 的验收标准写一条互相矛盾的话：slugify("A b") 必须同时返回 "a-b" 和 "a_b"。所以 reviewer 一定判 failed。
按流程走两轮。第二轮 reviewer 仍然 failed 后，再运行 attempt new，被拒绝就把拒绝理由原样告诉我，不要加 --human-approved，把请求设成 hitl（原因写两轮都失败），运行 check --require-conclusion。
builder 不用认真做，写一个最简单的 slug.py 就行。
```

## 人工检查项

- 第 3 次 `attempt new` 被拒绝，orchestrator 把拒绝理由原样告诉了你。
- 没有加 `--human-approved`。
- 如果 reviewer 判的是 blocked 而不是 failed，场景会不通过：照实告诉我。
- 测完删掉 `demo-b8/`（如果有）。

## 跑完以后

```text
python3 .harness/engine/cli.py eval check s3
```

默认检查最新的主会话和它的请求。要指定：`--session-id <会话 id>`（提示开头的规则里有，`cli.py stats` 的 `recent_sessions` 里有最近的会话 id），`--request <请求 id>`。

B8 的 S3 第一次测时，builder 和 reviewer 用了同一条矛盾标准，builder 先发现并交了 blocked，reviewer 一次没被调用。这里把矛盾只放给 reviewer。
