# 核心功能

harness 做五件事。每一件都分成“写给 agent 的说明”和“代码强制执行的检查”两层。说明会被模型忽略，检查不会。

## Task Level：按任务大小选工作方式

| Level | 用在 | agent 的做法 |
| --- | --- | --- |
| L1 | 确定的小任务 | 不用子 agent，搜索次数有上限 |
| L2 | 标准工程任务 | 先短计划；只在你写 `[verify]` 时才让 verifier 复核 |
| L3 | 复杂、需要独立验证的任务 | orchestrator 编排 builder 和 reviewer |

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
| CLI 专用文件 | `request.json`、`handoff.json`、`manifest.json`、`knowledge-brief.md`、报告，只能用命令改 |
| `.git` | 任何 Level 都不能写 `.git` 文件夹（含 Windows 的别名写法），也不能写目标仓库的 `refused_paths` |
| 危险终端命令 | 删根目录、`curl \| sh`、联网、装软件包、管理员权限等：拒绝或要你确认 |
| 批准类命令 | `approve-promote`、`recover`、`approve-command` 只能由你在终端运行，agent 运行会被拒绝 |
| 重复被拒 | 同一个拒绝出现多次，理由换成“停止重试”（熔断） |

gate 不是沙盒：终端命令可以用 gate 看不出的写法写任何路径。需要更强的隔离，用操作系统或容器。详细边界见 [.workspace/README.md](../.workspace/README.md)。规则全文在 [gate.json](../.harness/policies/gate.json)。

## L3 请求：多 agent 协作

一个请求是 `.workspace/sandbox/requests/<请求 id>/` 下的一个目录，由 CLI 建立和维护。

- **orchestrator** 计划、准备输入、调度、判断。**builder** 做成果。**reviewer** 独立验证，只看 builder 交上来的成果，不看过程（这条靠说明，没有硬拦截）。
- 每一轮（attempt）：orchestrator 填 assignment → `dispatch` 冻结输入包 → 调用子 agent → 子 agent 交 handoff。没有 `dispatch` 就调用子 agent 会被拒绝。
- reviewer 判 `passed`、`failed` 或 `blocked`。失败可以返工，轮数上限在 [orchestration.json](../.harness/policies/orchestration.json)。超过上限要你同意。
- 需要你决定时，orchestrator 运行 `request wait` 再结束这一轮；无法继续时进 HITL（人在回路）。
- 结束时必须有结论（`accepted`、`hitl`、`abandoned`），`check` 检查请求目录自洽，并自动写报告。
- 目录和文件的格式见 [04-reference.md](04-reference.md) 的 contracts 一节。

## 目标仓库：多个仓库，从 main 取文件，promote 回写

适用于公司的代码仓库不在 harness 里、文件很多不可能整个复制的场景。

- **取文件**：`request add-input --from-target <仓库>/<路径>` 用 `git` 读本地 main 分支（不动工作区），复制进沙箱。沙箱里路径第一段是仓库名。同一请求里每个仓库的提交在第一次读时固定。
- **分支**：每个请求有一个 `feature/<名字>` 分支名，所有被改的仓库用同一个。
- **promote**：先对每个仓库做检查：工作区干净、分支名没被占、main 上要改的文件没变、新文件在 main 上还不存在。所有仓库都通过才写。然后你在终端批准，再对每个仓库 `git switch -c <分支> <main>`，写文件，**不提交**。
- **备份**：成果和补丁备份在任务目录的 `DEV/`（`DEV/<仓库>/<路径>` 和 `<请求 id>.patch`）。
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
