# .workspace

agent 和人的工作区。这里的运行内容不进 git，只有本文件和四个 `.gitkeep`。

## 目录

| 路径 | 用途 | 谁写 |
| --- | --- | --- |
| `sandbox/requests/<request-id>/` | L3 请求的执行目录。L3 任务只在这里写 | L3 的 agent 和 CLI |
| `current_tasks/<任务>/` | 人放任务材料（`REQ/`、`REF/`）。L2 任务模式下：`PLAN.md`（计划）、`DEV/`（成果，路径和目标仓库一样）、`CHANGES.diff` 和 `PROMOTE-PLAN.diff`（给人看的差异）、`.task/`（状态） | 人；L2 的 agent 写 `PLAN.md` 和 `DEV/`；其余由 CLI 写 |
| `goals/<id>/` | 长任务的目标文件：`GOAL.md`（中心思想）、`TODO.md`（步骤）、`NOW.md`（进度指针）。用户输入 `/generic-goal-driven` 才建 | 人和 agent；L2 任务模式和 L3 进行中不能写 |
| `reports/` | 请求的执行报告。请求收尾时自动写，也可以 `cli.py report` 重写 | CLI |

`<request-id>` 的格式是 `<yyyymmdd-HHMM>-<slug>-<4 位随机>`。请求目录和里面的子目录都由 CLI 建立：`cli.py request new`、`attempt new`、`dispatch`。命令一览：`python .harness/engine/cli.py --help`（macOS/Linux 用 `python3`）。

L1、L2 不走 sandbox，直接在仓库里改。L2 的任务模式（`task start`）只写任务目录的 `PLAN.md` 和 `DEV/`，计划和回写都要人在终端批准。`sandbox/` 下请求目录之外的东西，是手测或探针留下的，可以直接删。

## 谁管着写入

规则在 [.harness/policies/gate.json](../.harness/policies/gate.json)，由 gate 模块在 PreToolUse 执行。
agent 要遵守的写法见 [workspace.instructions.md](../.github/instructions/workspace.instructions.md)。

- 所有 Level：guardrail 文件不能改。
- admin 模式（用户在终端运行 `admin on` 的那个会话）：guardrail 文件可以改，`.harness/runtime/` 除外。下面的其他规则不变。
- L3：编辑类工具只能写当前请求目录。写到别处会被拒绝，回写原仓库用 `promote`：先 `--dry-run`，用户在自己的终端运行 `request approve-promote` 批准，再 `promote`。开第一轮之前，计划要用户运行 `request approve-plan` 批准。
- L2 任务模式：用户运行 `task approve-plan` 之前，编辑类工具只能写 `PLAN.md`；之后只能写 `DEV/`。计划改了，批准失效。
- 所有 Level：目标仓库工作区里的文件不能直接改（编辑类工具，和带仓库完整路径的常见终端写法）。只有 promote 能写。
- 所有 Level：`request.json`、`handoff.json`、`manifest.json`、`knowledge-brief.md`、`promote-plan.diff`、任务目录的 `.task/` 和两个 `.diff`、`reports/` 下的报告只由 CLI 写，agent 直接写会被拒绝。
- 所有 Level：任何 `.git` 文件夹和目标仓库的 `refused_paths` 不能写（含终端写法）。配置了目标仓库后，agent 的 git 写命令要人批准，`push` 等永远不能批准，见 [docs/02-features.md](../docs/02-features.md)。
- gate 不管读取。skills、指令、知识库、contract 谁都能读。

## 管得住什么，管不住什么

| 能管住 | 管不住 |
| --- | --- |
| agent 用编辑类工具改 guardrail 文件，或在 L3 写到请求目录之外 | 终端命令可以写任何路径。gate 只拦常见写法（重定向、`rm`、`mv`、`sed -i`、`cp` 到 guardrail 路径等），拦不住所有写法 |
| 常见的危险终端命令：删根目录、`curl \| sh` 等（拒绝或要人确认）；git 写命令（要人批准，部分永远拒绝） | 子 agent 的调用也会触发 hook，但 hook 分不清是主 agent 还是子 agent。子 agent 的写入范围和主 agent 一样 |
| 同一个拒绝反复出现时，把拒绝理由换成"停止重试" | hook 只能拒绝，杀不掉一个一直重试的 agent。熔断靠那句话让它收尾 |
| 没开 admin 模式的会话改不了 guardrail：开关在 `.harness/runtime/` 的会话状态里，只有人在终端能开 | admin 模式的会话能改 engine 和策略，也就能改掉 gate 自己。它的底线靠 admin agent 的说明和你看差异，不靠 hook |
| 大小写、`..`、绝对路径、Windows 的 `\` 这些不同写法 | 间接写法，例如先 `cd` 进目录再用相对名字删除，或在脚本文件里写好再运行 |

需要更强的隔离，要用操作系统或容器层面的沙盒。gate 不是沙盒。
