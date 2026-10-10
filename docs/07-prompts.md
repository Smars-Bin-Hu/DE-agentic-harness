# 提示模板

给人用。复制一段，把尖括号里的内容换成你的，发给 Copilot Chat。

模板把最要紧的上下文写在提示里：需求在哪、改哪个仓库、知识库在哪、做到哪一步停。这样 agent 不用自己去猜，也不容易漏。

## 标记

写在提示里，hook 会读。

| 标记 | 写在哪 | 作用 |
| --- | --- | --- |
| `/l1` 或 `[L1]` | 提示开头 | 切到 L1：确定的小任务，直接做 |
| `/l2` 或 `[L2]` | 提示开头 | 切到 L2：先短计划再做 |
| `[verify]` | 提示里任意位置 | L2：做完后让 verifier 独立复核一次。任务模式里写一次就够，整个任务都有效 |
| `[no-verify]` | 提示里任意位置 | L2：这一条不复核。任务模式里写它，会把这个任务的复核关掉 |

Level 切换后一直有效，直到你再切。L3 不用标记：在 agent 下拉里选 `orchestrator`。

## L1：确定的小任务

不改目标仓库。适合查一个东西、解释一段代码、改 harness 仓库里的一个小文件。

```text
/l1 <一句话说清要做什么>。
文件：<路径>。
只做这一件事，不要扩展。
```

例：

```text
/l1 解释 <仓库名>/<路径>.sql 第 120 到 180 行在算什么，用 5 句话以内。
```

## L2：问答、RCA、出方案（不改文件）

不用任务目录。

```text
/l2 <问题或要分析的现象>。
范围：<仓库名>/<目录或文件>。
知识库：knowledge-base/，先读 knowledge-base/README.md，再按索引读 <domain 名> 相关的文件。
只分析，不改任何文件。
输出：<结论和依据的文件行号 / 一份方案的要点 / RCA 的原因和证据>。
```

想要独立复核结论，在末尾加 `[verify]`。

## L2 任务模式：RCA、设计、方案（成果存成文件，不改仓库）

想把结果留成文件、以后接着用时，带上任务目录。不需要计划和批准。

```text
/l2 <要分析的现象或要出的方案>。
任务目录：.workspace/current_tasks/<任务名>。需求在 REQ/<文件名>，参考在 REF/。
范围：<仓库名>/<目录或文件>。
知识库：knowledge-base/，先读 knowledge-base/README.md，再按索引读 <domain 名> 相关的文件。
不改目标仓库。把结果写到任务目录根下的 <RCA.md / DESIGN.md>。
```

## L2 任务模式：开发（日常主力）

先在 `.workspace/current_tasks/<任务名>/REQ/` 放好需求，参考代码放 `REF/`。

```text
/l2 [verify]
任务目录：.workspace/current_tasks/<任务名>。需求在 REQ/<文件名>，参考在 REF/。
目标仓库：<仓库名>。要改的范围大致在 <目录或文件>。
知识库：knowledge-base/，先读 knowledge-base/README.md，再读 <domain 名> 相关的文件。
按任务模式做：
1. task start，读需求和知识库，把计划写到 PLAN.md，然后停下，给我 PLAN.md 的链接，等我批准。
2. 我批准后，用 task fetch 取文件到 DEV/，只改计划里列的文件，不动别的逻辑，不重构。
3. 做完 task diff，再 task promote --dry-run，给我 PROMOTE-PLAN.diff 的链接，等我批准。
验收：<必须实现的功能；哪里必须能看到数据；不能影响的已有功能>。
```

说明：

- 不想复核就去掉 `[verify]`。
- 分支名默认是 `feature/<任务名>`，任务名里的 `-` 会变成 `_`。要别的，加一句：`分支名用 feature/<名字>`（字母、数字、下划线）。
- 两次批准都在你自己的终端：`harness task approve-plan`、`harness task approve-promote`。批准完回对话说“批准了”。
- 只要成果、不回写仓库：把第 3 步改成“做完 task diff，然后 task close”。

接着昨天的任务做（新对话）：

```text
/l2 接着做任务 .workspace/current_tasks/<任务名>。先 task start，再 task status，告诉我做到哪一步，然后继续。
```

回写之后还要再改一轮：

```text
/l2 任务 .workspace/current_tasks/<任务名> 上一轮已经回写。还要改：<新的要求>。
先 task start 开新的一轮，写新的 PLAN.md，停下等我批准。
```

## L2 任务模式：只测试或只复核

成果已经在 `DEV/` 里（你自己改的，或上一步做的）。

```text
/l2 [verify]
任务目录：.workspace/current_tasks/<任务名>。需求在 REQ/<文件名>。
DEV/ 里的成果已经写好。不要改文件。
运行 task diff，对照需求和 PLAN.md 检查：<检查项>。
把问题列出来，每条写文件和行号。
```

## L3：需要独立 reviewer 的任务

在 agent 下拉里选 `orchestrator`，再发：

```text
任务目录是 .workspace/current_tasks/<任务名>，需求在 REQ/<文件名>。
目标仓库是 <仓库名>。分支名用 feature/<名字>。
知识库路径为 knowledge-base/，入口是 knowledge-base/README.md，先读它，再读 <domain 名> 相关的文件。
请按流程：
1. 建请求，取文件，写计划，然后停下，给我 plan.md 的链接，等我批准。
2. 我批准后，派发 builder 和 reviewer，做到 reviewer 通过。
3. promote --dry-run，给我 promote-plan.diff 的链接，等我批准。
验收：<必须实现的功能；哪里必须能看到数据；不能影响的已有功能>。
```

说明：

- 两次批准都在你自己的终端：`harness request approve-plan --request <id>`、`harness request approve-promote --request <id>`。请求 id 在 agent 的回复里，也可以用 `harness request list` 看。
- 用了几轮、每轮的交接、被拒绝的调用，都在结束时的报告里。

## 长任务：目标驱动

任务大、会跨很多天或多个 session 时才用。只有你能启动，日常任务不要用。它把中心思想、步骤清单和进度写进 `.workspace/goals/<目标名>/`，每步做完等你说“通过”。

新建目标：

```text
/generic-goal-driven 目标：<要做成什么>。
背景：<需求在哪、涉及哪些仓库或 domain>。
整体验收：<做到什么程度算完成>。
先问我不清楚的地方，再拆步骤。拆好后给我文件链接，等我确认再开始第 1 步。
```

换了 session 或隔了几天，接着做：

```text
/generic-goal-driven 继续
```

加或改需求时，直接告诉 agent。它会先给你看影响哪些步骤，你确认后才改。

说明：

- 每一步由 agent 建议用 L1、L2 还是 L3，由你切换。
- 只有你在对话里说“通过”，步骤才算通过。
- 每步通过后，agent 在 `LOG.md` 记一条改了什么；步骤复杂时，交棒时会给你一份 `accept/` 里的验收指南，照着一步一步测。
- L2 任务模式和 L3 进行中，agent 写不了目标文件，要等任务或请求结束后再写。进行中提的新需求，先记在对话里。

## 什么时候用哪个

| 情况 | 用 |
| --- | --- |
| 查一个东西，解释一段代码 | L1 |
| RCA、读知识库、出方案，不改文件 | L2，不带任务目录 |
| RCA、设计、方案，要存成文件，不改目标仓库 | L2 任务模式，成果写在任务目录根下 |
| 需求清楚的开发，要改目标仓库 | L2 任务模式 |
| 跨多个仓库或 domain，改动大，想要独立的 reviewer 把关 | L3 |
| 改 harness 自己（hook、策略、engine、agent、skill），读报告，查 harness 出错的根因 | admin agent，先在终端 `admin on` |
