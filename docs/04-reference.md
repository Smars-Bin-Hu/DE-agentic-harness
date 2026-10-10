# 命令与字段参考

按代码写。命令用 `--help` 看全部参数。下面省略命令前面的 `harness`（短命令怎么配见 [快速开始](01-quickstart.md) 第 1 步）。

## 命令

### 给人用

| 命令 | 作用 |
| --- | --- |
| `--version` | 显示图案、版本、发布日期、作者。加 `--short` 只输出一行，例如 `harness 1.0.0`，给脚本用。都来自 `.harness/registry.json`；版本号格式 `主.次.修` |
| `user` | 用这份 harness 的人的名字，和它来自哪：`user.override.json`、`git`（`git config user.name`）或 `none` |
| `doctor` | 检查文件、策略、hook 配置、知识库、目标仓库是否一致 |
| `level status`、`level set` | 看或设会话的 Level（1 或 2）。只有人能设，agent 运行被拒绝 |
| `request approve-plan` | 批准 L3 请求的 `orchestrator/plan.md`。只能在终端，输入确认码 |
| `request approve-promote` | 批准最后一次 `promote --dry-run` 的计划。只能在终端，输入确认码 |
| `request recover` | promote 中途出错后，把仓库恢复原样。只能在终端，输入确认码 |
| `task approve-plan` | 批准 L2 任务的 `PLAN.md`。只能在终端，输入确认码 |
| `task approve-promote` | 批准最后一次 `task promote --dry-run` 的计划。只能在终端，输入确认码 |
| `task recover` | L2 任务的 promote 中途出错后，把仓库恢复原样。只能在终端，输入确认码 |
| `task status`、`task report` | 看 L2 任务做到哪一步；重写任务报告 |
| `approve-command` | 批准 agent 被拒绝的一条 git 命令。只能在终端，输入验证码 |
| `admin on` | 给一个会话开 admin 模式：它可以改 guardrail 文件。只能在终端，输入确认码 |
| `admin off`、`admin status` | 关掉一个会话的 admin 模式；列出开着 admin 模式的会话 |
| `request list`、`request show` | 看请求列表和某个请求的 `request.json` |
| `target list`、`target show` | 看目标仓库：路径、base 分支、提交号、工作区是否干净 |
| `report` | 重写某个请求的报告 |
| `stats` | 日志汇总：调用数、拒绝数、各模块的拒绝 |
| `logs prune` | 删除 N 天没写过的会话日志（`--dry-run` 先看） |
| `eval list`、`eval show`、`eval check` | 固定场景：列出、给提示、判断一次运行 |

### agent 在 L2 任务模式里用

| 命令 | 作用 |
| --- | --- |
| `task start` | 进入任务模式：开始、接着做，或在回写过之后开新的一轮。只在 L2 |
| `task fetch` | 把目标仓库 main 上的文件取到 `DEV/<仓库>/<路径>`；`--overwrite` 丢掉改动重新取 |
| `task delete` | 声明删除一个取过的文件 |
| `task diff` | 列出 `DEV/` 的改动，差异全文写到 `CHANGES.diff` |
| `task set-branch` | 改 feature 分支名。格式是 `feature/` 加字母、数字、下划线（最长 60 个字符），不能有 `-`、`.`、`/`。默认取任务目录名，其中不合格的字符变成 `_`（`my-task` 变成 `feature/my_task`）；任务开新一轮时加 `_r2`、`_r3` |
| `task promote` | 把 `DEV/<仓库>/` 下的文件回写到各目标仓库的新分支；`--dry-run` 只列计划，差异写到 `PROMOTE-PLAN.diff`。直接放在 `DEV/` 根目录的文件不回写 |
| `task close` | 退出任务模式，写报告 |

### agent 在 L3 里用

| 命令 | 作用 |
| --- | --- |
| `request new` | 建请求，会话进入 L3。可带 `--task`、`--branch` |
| `request add-input` | 把文件复制进 `init-inputs/`；`--from-target <仓库>/<路径>` 从目标仓库的 main 取 |
| `request set-branch` | 设 feature 分支名 |
| `request wait` | 声明在等人，agent 可以结束这一轮 |
| `request set-status` | 给结论：`accepted`、`hitl`、`abandoned` |
| `brief set` | 交知识简报 |
| `attempt new` | 开下一轮。计划没有经人批准（`request approve-plan`）会被拒绝 |
| `dispatch` | 冻结一个角色的输入包 |
| `handoff submit` | builder 或 reviewer 交 handoff |
| `check` | 检查请求目录自洽；`--require-conclusion` 还要求有结论 |
| `promote` | 把 reviewer 通过的成果回写；`--dry-run` 只列计划，差异写到 `promote-plan.diff` |

## 策略字段

默认值在 `.harness/policies/<文件>`，覆盖写在同名 `.override.json`。数字都在这些文件里，这里不重复。

| 文件 | 字段 | 含义 |
| --- | --- | --- |
| task-levels.json | `switch_markers` | 切换 Level 的提示标记 |
| task-levels.json | `levels.1.budget_per_prompt.repository_searches.limit` | L1 每条提示的搜索次数上限（`on_exceed`：`deny` 或 `warn`） |
| task-levels.json | `levels.1.budget_per_prompt.observed_tool_calls.limit` | 每条提示的工具调用提醒线 |
| task-levels.json | `levels.2.subagents.allowed` | L2 允许的子 agent |
| task-levels.json | `levels.2.verification.enabled` | verifier 复核默认开不开 |
| task-levels.json | `levels.2.verification.enable_markers` | 开启复核的提示标记 |
| task-levels.json | `levels.2.verification.skip_markers` | 跳过复核的提示标记 |
| task-levels.json | `levels.2.verification.require_when.edits` | 本条提示改了文件，就要求复核 |
| task-levels.json | `levels.2.verification.require_when.min_tool_calls` | 工具调用达到这个数，也要求复核 |
| task-levels.json | `levels.3.subagents.allowed` | L3 允许的子 agent（builder、reviewer） |
| task-levels.json | `levels.3.subagents.require_dispatch` | 调子 agent 前必须 `dispatch` |
| gate.json | `guardrail_paths` | 所有 Level 都不能改的路径 |
| gate.json | `extra_guardrail_paths` | 你追加的 guardrail 路径 |
| gate.json | `admin_locked_paths` | admin 模式下也不能改的 guardrail 路径。`.harness/runtime/**` 删不掉 |
| gate.json | `cli_owned_paths` | 只有 CLI 能写的路径 |
| gate.json | `l3_write_root` | L3 的可写目录，含 `{request_id}` |
| gate.json | `terminal.guardrail_write` | 终端命令写 guardrail 的识别规则 |
| gate.json | `terminal.deny` | 直接拒绝的终端命令 |
| gate.json | `terminal.ask` | 要你确认的终端命令 |
| gate.json | `git.approval_minutes` | git 命令批准后的有效分钟数 |
| gate.json | `circuit_breaker.repeat_limit` | 同一个拒绝出现几次后换成“停止重试” |
| orchestration.json | `max_attempts` | 一个请求最多几轮 |
| orchestration.json | `brief.max_bytes` | 知识简报的大小上限 |
| orchestration.json | `brief.max_entries` | 知识简报的条数上限 |
| orchestration.json | `handoff.summary_max_lines` | handoff 摘要的行数上限 |
| orchestration.json | `inputs.max_files` | 输入文件数上限 |
| orchestration.json | `verify.main_stop` | 请求没结论时，主 agent 结束前拦一次 |
| orchestration.json | `verify.subagent_stop` | 子 agent 没交 handoff 时的处理：`block`、`log`、`off` |
| observe.json | `max_text_chars` | 日志里每段文字的最大长度 |
| observe.json | `capture.enabled` | 保存 hook 的原始输入输出 |
| observe.json | `warn_session_files` | 会话日志文件数超过它时 `doctor` 提醒 |
| user.json | `name` | 你的名字。agent 在要署名的地方用（例如文件开头的改动记录）。空着就用 `git config user.name` |
| cli.json | `output.encoding` | CLI 输出的编码。`auto`（默认）跟着终端；`utf-8` 一律输出 UTF-8 |
| agents.json | `series` | 模型系列 |
| agents.json | `different_series` | 必须用不同系列的角色组 |
| agents.json | `any_series` | 回退列表可以跨系列的 agent（admin） |
| target.json | `repos_root` | 目标仓库的父文件夹 |
| target.json | `repos` | 单个仓库的 `path`、`base_ref`、`refused_paths` |
| target.json | `base_ref` | 取文件的分支 |
| target.json | `refused_paths` | 不许回写、agent 也不能直接写的路径 |
| target.json | `git_timeout_seconds` | 每条 git 命令的超时 |

## 交接格式（contracts）

`.harness/contracts/` 里是 JSON Schema，CLI 写文件时按它校验。

| 文件 | 内容 |
| --- | --- |
| `request.schema.json` | `request.json`：状态、轮次、输入、计划的批准、promote 状态、分支、目标仓库 |
| `manifest.schema.json` | 输入包清单：每个文件的路径、用途（input、candidate、base、diff、deleted、previous-attempt）、sha256；目标仓库文件还有仓库名、blob、提交号 |
| `handoff.schema.json` | builder 和 reviewer 的交接：`status`（passed、failed、blocked）、成果、`deletes`（builder 声明要删除的目标仓库文件，没有就没这个字段）、证据、阻塞、建议 |
| `templates/assignment.md` | orchestrator 给角色的任务书模板 |

## hook 事件

配置在 [.github/hooks/harness.json](../.github/hooks/harness.json)，全部指向 `hook.py`。

| 事件 | 谁处理 |
| --- | --- |
| `SessionStart` | task_level（建会话状态） |
| `UserPromptSubmit` | task_level（读 Level 标记、注入规则）、request（L2 任务做到哪一步） |
| `PreToolUse` | task_level（预算、子 agent）、gate（含 L2 任务的写入范围）、request（子 agent 要先 dispatch） |
| `PostToolUse` | task_level（计数） |
| `SubagentStart`、`SubagentStop` | request（记录启动、检查 handoff；告诉 L2 任务的 verifier 读差异） |
| `Stop` | task_level、request（请求没结论、没标等待时拦一次） |

## 运行时文件

都在 `.harness/runtime/`，不进 git，agent 不能写（admin 模式也不能）。

| 路径 | 内容 |
| --- | --- |
| `state/<surface>/<会话>.json` | 每个会话的 Level、当前请求、子 agent、预算计数、是否在 admin 模式 |
| `logs/<surface>/<会话>.jsonl` | 会话日志 |
| `logs/hook-errors.jsonl` | hook 自己出的错 |
| `git-approvals.json` | 等待批准和已批准的 git 命令 |
| `capture/` | `capture.enabled` 打开时的原始 hook 输入输出 |

`<surface>` 是 `vscode` 或 `cli`，由 hook 识别运行环境后写入。

## 工作区

| 路径 | 内容 |
| --- | --- |
| `.workspace/sandbox/requests/<请求 id>/` | L3 请求目录，由 CLI 建立 |
| `.workspace/current_tasks/<任务>/` | 你放任务材料（需求、参考、测试数据）；promote 把备份写进它的 `DEV/` |
| `.workspace/reports/` | 请求报告，由 CLI 写 |
| `.workspace/goals/<目标名>/` | 长任务的 `GOAL.md`、`TODO.md`、`NOW.md`、`LOG.md`、`accept/`，用 `/generic-goal-driven` 才建；L2 任务模式和 L3 进行中不能写 |
