---
name: harness-orchestration
description: 'L3 请求的完整流程：建立请求、准备输入和知识简报、派发 builder 和 reviewer、读 handoff、返工、人工批准的 promote、结束。orchestrator 在 L3 里按它做。用户提到 L3、orchestrator、请求目录、dispatch、handoff、promote 时使用。'
type: workflow
specificTo: harness-orchestration
---

# L3 请求流程

只有 orchestrator 用这个流程。所有数字（轮数、brief 大小、摘要行数）在 `.harness/policies/orchestration.json`，这里不写。
`<cli>` 是 `python .harness/engine/cli.py`（Windows）或 `python3 .harness/engine/cli.py`（macOS/Linux）。提示开头的规则里也写了它。命令一览：`<cli> --help`。下面省略命令前的 `<cli>`。

## 一条原则

目录、复制、计数、上限和检查都由 CLI 做。你只判断和写内容。CLI 拒绝时，理由里有下一步，照做。

## 步骤

1. **建请求**：`request new --title "<短标题>" --session-id <提示开头规则里的会话 id>`。记下 `request_id`，之后每条命令都带 `--request`。用户给了任务目录就加 `--task .workspace/current_tasks/<任务名>`。
2. **准备输入**：`request add-input <文件或目录>...` 把需求和必要文件复制进 `init-inputs/`。第一次 dispatch 之后就不能再加。
   配置了目标仓库时，输出里有 `target_repos`。要改仓库里的文件，用 `--from-target <仓库名>/<路径>`（文件或目录，可重复）取它们 main 上的版本，不要自己复制。builder 的成果路径第一段也是仓库名。要删除或改名的文件也要取（builder 用 `--delete` 声明删除，改名 = 新文件加删除旧文件）。分支名用户说了就 `request set-branch --request <id> --branch feature/<名字>`（字母、数字、下划线），promote 之前必须设好。
3. **知识简报**：先用读文件的工具打开 `knowledge-base/README.md`（不要用搜索或列目录判断有没有：被 git 忽略的目录搜不到）。README 只是占位说明、没有索引，才算知识库为空。用户的提示里写了知识库路径，就以它为准。
   知识库有内容时，把和本任务有关的结论蒸馏成一份文件，每条一行：`- 结论 [来源: 文件路径#章节]`。写在请求目录里（例如 `orchestrator/brief-draft.md`），用 `brief set <文件>` 交给 CLI。没有来源的条目会被拒绝。按知识库自己的索引和 instructions 选文件，不要整篇复制。返工的轮次只补缺的条目，不重写旧的。
   不论写不写 brief，都要在第 4 步的 `plan.md` 里用一句话写明知识库的结论：用了哪些文件，或者为什么都无关。
4. **计划**：写 `orchestrator/plan.md`。哪个角色明显不适用，就在这里写理由。
5. **开一轮**：`attempt new`。它建好两个角色的输入包，里面各有一份 `assignment.md` 模板。
6. **填 builder 的 assignment**：目标和验收标准必填，去掉所有“（待填）”。验收标准要具体到 reviewer 能照着验证。
7. **派发 builder**：`dispatch --role builder [--input <文件>]... [--from-target <仓库名>/<路径>]...`。包随即变成只读。然后调用 builder 子 agent。没有 dispatch 就调用会被拒绝。
8. **读 builder 的 handoff**：在 `handoffs/builder/attempt-NNN/handoff.json`。
   - `passed`：继续。
   - `failed` 或 `blocked`：看 `blockers`。能修就 `attempt new` 返工；缺的东西要用户给，就进 HITL。
9. **派发 reviewer**：`dispatch --role reviewer`。reviewer 的 assignment 不用填：CLI 把 builder 的目标和验收标准抄过去（输出里有 `assignment_copied_from_builder`）；reviewer 要不同的验收标准，才在派发前自己填。CLI 把 builder 列出的成果复制到 `candidate/`；目标仓库的请求还会生成 `candidate.diff`（成果和 main 的差异）。然后调用 reviewer 子 agent。
10. **读 reviewer 的 handoff**：
    - `passed`：去第 12 步。
    - `failed`：问题明确、能修，就读 `kb_additions`，需要的话在 brief 里补增量（再 `brief set`），`attempt new`，回到第 6 步。
    - `blocked`：缺什么就补什么；补不了就进 HITL。
11. **上限**：`attempt new` 到了上限会被拒绝。先 `request wait --request <id> --reason "等用户决定要不要继续"`，再问用户要不要继续。用户同意，才加 `--human-approved "<原因>"`。用户不同意，或要改需求，就进 HITL。
12. **回写**：
    1. `promote --request <id> --dry-run`，列出要写的文件和每个文件增删的行数（不带差异，差异用户在批准屏幕上看）。
    2. 先 `request wait --request <id> --reason "等用户批准 promote"`。把计划给用户看，原样给出这条命令，请用户**在自己的终端**运行：`request approve-promote --request <id>`，看计划，输入确认码。你不能自己运行它。
    3. 用户说批准了，再 `promote --request <id>`。
    4. 请求有目标仓库时，`promote` 在每个仓库里从 main 新建请求的分支，把成果写进去，**不提交**。先检查所有仓库（工作区干净、分支名没被占、main 上的文件没变），任何一个不通过，什么都不写，信息里列出所有问题；照着做，或告诉用户，再 `promote --dry-run`。成果和补丁备份在任务目录的 `DEV/`。提交由用户自己做。
    5. promote 中途出错（`promote.state` 是 `partial`）：不要重试，不要 `set-status`。把错误里的“已写好、出错、没动”和恢复方法原样给用户：请用户**在自己的终端**运行 `request recover --request <id>`（你不能自己运行它）；恢复后再 `promote --dry-run`，请用户重新批准。
13. **结束**：`request set-status --request <id> --status accepted`（reviewer 通过并已回写）。成果还没 promote 时，CLI 拒绝 accepted。然后 `check --request <id> --require-conclusion`。会话回到 L1。
    `set-status` 会自动写报告，输出里的 `report` 是路径。把它告诉用户。`report --request <id>` 可以随时重写。

## 等用户

要把问题交给用户、结束这一轮时（批准 promote、HITL 的提问、要用户决定），先运行 `request wait --request <id> --reason "<等什么>"`，再结束。
请求还是 open 又没标等待，你结束时会被拦一次，理由里有这两条路。用户的下一条提示到达时，等待标记自动清除。

## 进入 HITL

`request set-status --status hitl --reason "<原因>"`，并把原因告诉用户。下面任一情况都要进：

- 要改变原始需求或验收标准。
- 要用户决定是否接受缺陷或做取舍。
- 涉及高风险、不可恢复的操作，或权限要扩大。
- 最后一轮 reviewer 仍然失败或阻塞，而且用户不同意再来一轮。
- 预计要超出时间、token 或工具调用的预算。

不要重置计数，也不要用重建请求来绕过上限。

## 成本

- 每次调用 builder 或 reviewer 都消耗一次 dispatch。调用次数由 attempt 上限自然限制。
- 调用子 agent 前，把工具的必填参数填全。子 agent 没有真正启动（比如工具说缺参数）时，补齐参数直接再调用一次，不用重新 dispatch。子 agent 一旦启动，同一次 dispatch 不能再调用。
- 输入包里只放当前角色用得上的内容。同一个请求里，所有轮次和两个角色共用同一份 brief。
- 触发成本警告后，先判断是收窄范围、进入 HITL 还是停止。

## 被拒绝时

- 写 `request.json`、`handoff.json`、`manifest.json`、`knowledge-brief.md`：被拒绝，用对应的命令。
- 写请求目录之外的文件：被拒绝，改在请求目录里写，要回写用 `promote`。
- 同一个拒绝出现多次：停止重试，告诉用户被什么拦住了。

## 不要做

- 不自己写 builder 的成果，不改 reviewer 的结论。
- 不调用 builder、reviewer 之外的子 agent。
- 不自己批准 promote。
