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

## L2 的任务模式

用户指定了任务目录 `.workspace/current_tasks/<任务>`，并要你产出或修改文件时用。只是问答、RCA、出方案、不改文件时不用，照常做。
`<cli>` 是 `python .harness/engine/cli.py`（Windows）或 `python3 .harness/engine/cli.py`（macOS/Linux）。下面省略命令前的 `<cli>`。

1. **开始**：`task start --task .workspace/current_tasks/<任务> --session-id <提示开头规则里的会话 id>`。它建好 `DEV/`。以前做过的任务会接着做；上一轮已经回写过，就开新的一轮。
2. **读**：任务目录的 `REQ/`、`REF/`；知识库先读 `knowledge-base/README.md` 再按索引读需要的；目标仓库只读（main 上的版本用 `git -C <仓库> show main:<路径>`，大文件只读需要的部分）。
3. **写计划，然后停下**：把计划写到 `<任务>/PLAN.md`：要改哪些文件、每个文件怎么改、怎么验收、用了知识库的哪些结论、不改什么。写完用两三句话告诉用户要点，给出链接 `[PLAN.md](.workspace/current_tasks/<任务>/PLAN.md)`，请用户**在自己的终端**运行 `task approve-plan`。你不能自己运行它。不要把计划全文贴进对话。
4. **用户说批准了，再动手**。批准前只能写 `PLAN.md`；批准后只能写 `<任务>/DEV/`。计划改了要重新批准。
5. **取文件**：目标仓库的文件用 `task fetch <仓库名>/<路径>...` 取到 `DEV/<仓库名>/<路径>`（和仓库里的路径一样）。在那里改。新文件直接建在 `DEV/<仓库名>/<路径>`。要删除的文件先取，再 `task delete <仓库名>/<路径>`。改名是新文件加删除旧文件。只改计划里列的文件，不顺手改别的。
6. **自查**：`task diff` 列出每个文件的增删行数，差异全文在 `CHANGES.diff`。用户写了 `[verify]` 就调用 verifier。
7. **回写**（配置了目标仓库时）：`task promote --dry-run`。把文件清单告诉用户，给出输出里 `review_file`（`PROMOTE-PLAN.diff`）的链接，请用户**在自己的终端**运行 `task approve-promote`。用户说批准了，再 `task promote`。它在每个仓库里从 main 新建分支（默认 `feature/<任务目录名>`），写入文件，**不提交**。
   中途出错时不要重试：把错误原样给用户，请用户在终端运行 `task recover`。
8. **结束**：`task close`。输出里的 `report` 是报告路径，告诉用户。

目标仓库里的文件任何 Level 都不能直接改，编辑工具和常见的终端写法都会被拒绝。不用 `rm` 清理文件。
随时用 `task status` 看做到哪一步。

## L2 的复核

复核默认关闭，由用户开启。每条提示开头的规则会写明本条提示开没开。
没开：自己检查交付物，不要调用子 agent。需要独立复核时，停下来建议用户在提示里写 `[verify]`。

开了，并且本条提示改了文件或工具调用较多时，结束前要调用 verifier 复核一次（具体条件在规则里）：

1. 最后一次修改之后再调用。`agentName` 填 `verifier`。
2. 简报写三项：用户的原话、交付物（改了哪些文件，或答案的关键结论和出处）、检查项（要跑的测试、要核对的结论）。
   不要写你的推理过程，只给结果。
3. 第一行是 `VERDICT: PASS`：照常结束。
4. 第一行是 `VERDICT: FAIL`：照它列出的问题修复，再复核一次。第二次仍是 FAIL，就停下来，把问题原样交给用户。
5. 用户在提示里写了 `[no-verify]`，本条提示不用复核。
6. 没改文件、读得也少的问答不需要复核。

## 三个 Level

- **L1，确定任务**：目标、修改点和验证方式都清楚。不写计划，只读必要的内容，直接动手。不用子 agent。
- **L2，标准工程任务**：要看几个相关文件、写短计划。只探索相关区域。子 agent 只允许 verifier，而且只在用户写了 `[verify]` 时。用户指定了任务目录并要改文件时，走任务模式。
- **L3，复杂或编排任务**：跨子系统、复杂 RCA、需要独立验证。由用户切到 orchestrator 进入，不能用标记进入。

具体数字（搜索次数、工具调用次数、子 agent 次数）只在 `.harness/policies/task-levels.json`。
更多说明见 [references/task-level.md](references/task-level.md)。
