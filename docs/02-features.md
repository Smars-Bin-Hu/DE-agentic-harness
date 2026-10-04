# 核心功能

harness 做六件事。每一件都分成“写给 agent 的说明”和“代码强制执行的检查”两层。说明会被模型忽略，检查不会。

## Task Level：按任务大小选工作方式

| Level | 用在 | agent 的做法 |
| --- | --- | --- |
| L1 | 确定的小任务 | 不用子 agent，搜索次数有上限 |
| L2 | 标准工程任务：开发、测试、RCA、出方案 | 先短计划；只在你写 `[verify]` 时才让 verifier 复核。指定了任务目录并要改文件时走任务模式 |
| L3 | 复杂、需要独立验证的任务 | orchestrator 编排 builder 和 reviewer |

- 怎么选：需求清楚的中小任务用 L1、L2；要改目标仓库就用 L2 的任务模式，计划和回写都由你批准，有报告。L3 更贵，多出来的是独立的 reviewer 和每一步的交接记录。实测数字见 [省时间和省钱](06-cost-optimization.md) 的第九节。
- 任务大到要跨很多天或多个 session：用 `/generic-goal-driven`，见下面“长任务：目标驱动”。它只管记录和流程，不改 Level 和权限。
- 上限和标记在 [task-levels.json](../.harness/policies/task-levels.json)。
- Level 只控制工作方式，不改文件、网络、环境、生产权限。
- 只有你能切换。hook 读你的提示原文来识别标记，agent 运行 `level set` 会被拒绝。
- 超出上限时，hook 拒绝或提醒（见 `on_exceed`）。

## gate：拦住危险的写和命令

gate 是一个 hook 模块，在每次工具调用前检查。它只管写，不管读。

| 它拦 | 说明 |
| --- | --- |
| guardrail 文件 | `.github/hooks/`、`.harness/engine/`、`.harness/policies/`、`.harness/bin/`、`.harness/registry.json`、`.harness/runtime/`、`.vscode/settings.json`。所有 Level 都不能改，也不能被 override 删掉 |
| L3 越界写 | L3 的编辑类工具只能写当前请求目录 |
| L2 任务越界写 | 任务模式下，你批准计划之前只能写 `PLAN.md`，之后只能写任务的 `DEV/` |
| 目标仓库的工作区 | 任何 Level 都不能直接改目标仓库里的文件，只有 promote 能写 |
| CLI 专用文件 | `request.json`、`handoff.json`、`manifest.json`、`knowledge-brief.md`、报告，只能用命令改 |
| `.git` | 任何 Level 都不能写 `.git` 文件夹（含 Windows 的别名写法），也不能写目标仓库的 `refused_paths` |
| 危险终端命令 | 删根目录、`curl \| sh`、联网、装软件包、管理员权限等：拒绝或要你确认 |
| 批准类命令 | `approve-plan`、`approve-promote`、`recover`、`approve-command` 只能由你在终端运行，agent 运行会被拒绝 |
| 重复被拒 | 同一个拒绝出现多次，理由换成“停止重试”（熔断） |

gate 不是沙盒：终端命令可以用 gate 看不出的写法写任何路径。需要更强的隔离，用操作系统或容器。详细边界见 [.workspace/README.md](../.workspace/README.md)。规则全文在 [gate.json](../.harness/policies/gate.json)。

## L2 任务模式：一个 agent，两次批准

日常开发用它。你在提示里指定任务目录 `.workspace/current_tasks/<任务>`，并要 agent 产出或修改文件时，agent 运行 `task start` 进入任务模式。没有指定任务目录的 L2（问答、RCA、出方案）不受影响。

- **计划要你批准**：agent 把计划写到 `<任务>/PLAN.md` 就停下，给你文件的链接。你在编辑器里看，在终端运行 `task approve-plan`，输入确认码。确认码绑定这份计划，计划改了要重新批准。
- **只写 `DEV/`**：批准之前，编辑类工具只能写 `PLAN.md`；批准之后只能写 `<任务>/DEV/`。
- **取文件**：`task fetch <仓库>/<路径>` 从本地 main 读文件（不动工作区），放到 `DEV/<仓库>/<路径>`，路径和仓库里一样。几 MB 的大文件按字节原样复制。
- **差异**：`task diff` 把成果和取文件时的版本对比，写成 `CHANGES.diff`。verifier 读差异，不读全文。
- **回写要你批准**：`task promote --dry-run` 把完整差异写成 `PROMOTE-PLAN.diff`，你在编辑器里看，在终端运行 `task approve-promote`。检查、新分支（默认 `feature/<任务名>`）、不提交、出错恢复，都和 L3 的 promote 一样。
- **删除和改名**：`task delete <仓库>/<路径>` 声明删除（文件要先取过）。改名是新文件加删除旧文件。
- **多轮**：接着做沿用原来的批准。回写过之后再 `task start`，开新的一轮：上一轮的成果移到 `DEV_r<轮数>/`，要新计划、新批准。
- **报告**：`task close` 写 `.workspace/reports/task-<任务名>.md`：计划全文、两次批准的时间、取了哪些文件、改动的增删行数、verifier 结论、被拒绝的调用。

和 L3 的差别：没有请求目录，没有 handoff，没有独立的 reviewer。复核是可选的 verifier。

## L3 请求：多 agent 协作

一个请求是 `.workspace/sandbox/requests/<请求 id>/` 下的一个目录，由 CLI 建立和维护。

- **orchestrator** 计划、准备输入、调度、判断。**builder** 做成果。**reviewer** 独立验证，只看 builder 交上来的成果，不看过程（这条靠说明，没有硬拦截）。
- **计划要你批准**：orchestrator 写完 `orchestrator/plan.md` 就停下，给你文件的链接。你在终端运行 `request approve-plan`。没批准不能开第一轮；计划改了要重新批准；计划没变的返工轮不用。
- 每一轮（attempt）：orchestrator 填 assignment → `dispatch` 冻结输入包 → 调用子 agent → 子 agent 交 handoff。没有 `dispatch` 就调用子 agent 会被拒绝。
- reviewer 判 `passed`、`failed` 或 `blocked`。失败可以返工，轮数上限在 [orchestration.json](../.harness/policies/orchestration.json)。超过上限要你同意。
- 目标仓库的请求里，reviewer 的输入包多一份 `candidate.diff`（成果和 main 的差异，只有改动的行），让它先读差异，不用把整个文件读两遍。reviewer 的任务书默认抄 builder 的目标和验收标准，不用写两遍。
- 需要你决定时，orchestrator 运行 `request wait` 再结束这一轮；无法继续时进 HITL（人在回路）。
- 结束时必须有结论（`accepted`、`hitl`、`abandoned`），`check` 检查请求目录自洽，并自动写报告。
- 目录和文件的格式见 [04-reference.md](04-reference.md) 的 contracts 一节。

## 长任务：目标驱动（可选，只有你能启动）

任务大、会跨很多天或多个 session 时，agent 容易忘。输入 `/generic-goal-driven`，它把任务存成三个文件，放在 `.workspace/goals/<目标名>/`（git 忽略）：

| 文件 | 内容 |
| --- | --- |
| `GOAL.md` | 中心思想：目标、原则、范围、不做什么、整体验收；末尾是变更记录 |
| `TODO.md` | 步骤清单：每步的状态、验收标准、你的反馈 |
| `NOW.md` | 进度指针：现在在哪一步、下一步做什么 |

- **一步一步做**：每步做完自验，交给你验收。**只有你在对话里说“通过”，步骤才算通过**，然后才开下一步。每步由 agent 建议用 L1、L2 还是 L3，由你切换。
- **能随时接上**：换了 session 或隔了几天，输入 `/generic-goal-driven 继续`。agent 读 `NOW.md` 和 `TODO.md`，核对磁盘，记录和磁盘不一致时以磁盘为准，汇报后等你说开始。
- **能改需求**：直接告诉 agent。它先给你看影响哪些步骤，你确认后才改。已通过的步骤不改写，要返工就加新步骤，变更记在 `GOAL.md` 末尾。
- **和 gate 的关系**：L2 任务模式和 L3 请求进行中，gate 不许写这三个文件。agent 在开工前写好 `NOW.md`，任务或请求结束后再更新。进行中你提的新需求，先记在对话里。
- **日常任务不要用**：agent 觉得任务很长时，只能建议，不能自己启动。
- 提示模板见 [07-prompts.md](07-prompts.md)，技能在 [.github/skills/generic-goal-driven/](../.github/skills/generic-goal-driven/)。

## 目标仓库：多个仓库，从 main 取文件，promote 回写

适用于公司的代码仓库不在 harness 里、文件很多不可能整个复制的场景。典型的是数据工程 pipeline 代码库：没有入口、不能在本机运行，按 domain 或功能存放大量 Python、SQL、`.json` 配置、`.sh` 和 PowerShell 脚本。详见 [配置与定制](03-configure.md) 的“适用的代码库”。

- **取文件**：`request add-input --from-target <仓库>/<路径>` 用 `git` 读本地 main 分支（不动工作区），复制进沙箱。沙箱里路径第一段是仓库名。同一请求里每个仓库的提交在第一次读时固定。
- **分支**：每个请求有一个 `feature/<名字>` 分支名，所有被改的仓库用同一个。
- **promote**：`--dry-run` 给 agent 的输出只有文件清单和增删行数；完整差异写在请求目录的 `promote-plan.diff`，你在编辑器里看。批准屏幕只列文件和这个文件的路径。先对每个仓库做检查：工作区干净、分支名没被占、main 上要改的文件没变、新文件在 main 上还不存在。所有仓库都通过才写。然后你在终端批准，再对每个仓库 `git switch -c <分支> <main>`，写文件，**不提交**。
- **删除和改名**：builder 交接时用 `--delete <仓库>/<路径>` 声明要删的文件（必须是取过的）。reviewer 在 `candidate.diff` 里看到“deleted file”；计划里的动作是 `delete`，批准屏幕上会提醒；写的时候文件在新分支上被删掉，空文件夹一起清掉。改名就是新文件加删除旧文件。
- **备份**：成果和补丁备份在任务目录的 `DEV/`（`DEV/<仓库>/<路径>` 和 `<请求 id>.patch`；被删的文件放在 `DEV/_deleted/`）。
- **中途出错**：不自动回滚。请求进入 `partial`，你在终端运行 `request recover` 恢复。
- 没配置目标仓库时，请求沿用 harness 自己的仓库：成果的路径就是仓库里的路径，promote 同样要你批准；guardrail 路径和 `.workspace/` 不能回写。

## git 命令：读放行，写要你批准

配置了目标仓库后，agent 在终端里运行 git：

- **读**（`status`、`diff`、`log`、`show`、只列出的 `branch`……）：直接放行。
- **写**（`add`、`commit`、`switch`、`merge`……）：被拒绝，理由里有整条命令和验证码。你运行 `approve-command`，看命令原文，输入验证码。同一会话里同一条命令在 `gate.json` 的 `git.approval_minutes` 分钟内放行一次。
- **永远不能批准**：`push`、`gh pr`、`reset --hard`、`clean`、`branch -D`、任何强制选项（`--force`、`-f`）等。agent 要停下来告诉你，由你自己运行。

## 可观测：日志、统计、报告、场景检查

- 每个会话一个日志文件：`.harness/runtime/logs/<surface>/`。不记工具参数，被拒绝的调用才记路径和命令（长度限制见 [observe.json](../.harness/policies/observe.json)）。
- `stats` 汇总调用数、拒绝数、哪个模块拒绝的；`logs prune` 清理旧日志。
- 请求结束时自动写 `.workspace/reports/<请求 id>.md`：结果、每轮、每个 handoff、被拒绝的调用。
- `eval` 是固定场景：`eval show` 给出提示和要做的事，你在 Copilot 里跑一遍，`eval check` 根据日志和请求目录判断对不对。

## hook 怎么接进来

所有 hook 事件走同一个入口 [hook.py](../.harness/engine/hook.py)。它识别运行环境（VS Code 的本地会话和 Copilot SDK 会话发来的内容格式不同），把事件分发给模块，合并结果。模块清单和开关在 [registry.json](../.harness/registry.json)。hook 自己出错时放行，并写入 `hook-errors.jsonl`，不会误伤正常工作。
