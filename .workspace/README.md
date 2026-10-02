# .workspace

agent 和人的工作区。这里的运行内容不进 git，只有本文件和三个 `.gitkeep`。

## 目录

| 路径 | 用途 | 谁写 |
| --- | --- | --- |
| `sandbox/requests/<request-id>/` | L3 请求的执行目录。L3 任务只在这里写 | L3 的 agent 和 CLI |
| `current_tasks/` | 人放任务材料 | 人 |
| `reports/` | 请求的执行报告 | CLI |

`<request-id>` 的格式是 `<yyyymmdd-HHMM>-<slug>-<4 位随机>`。请求目录里的子目录由 `cli.py request new` 建立。

L1、L2 不走 sandbox，直接在仓库里改。`sandbox/` 下请求目录之外的东西，是手测或探针留下的，可以直接删。

## 谁管着写入

规则在 [.harness/policies/gate.json](../.harness/policies/gate.json)，由 gate 模块在 PreToolUse 执行。
agent 要遵守的写法见 [workspace.instructions.md](../.github/instructions/workspace.instructions.md)。

- 所有 Level：guardrail 文件不能改。
- L3：编辑类工具只能写当前请求目录。写到别处会被拒绝，回写原仓库用 `promote`，要人确认。
- gate 不管读取。skills、指令、知识库、contract 谁都能读。

## 管得住什么，管不住什么

| 能管住 | 管不住 |
| --- | --- |
| agent 用编辑类工具改 guardrail 文件，或在 L3 写到请求目录之外 | 终端命令可以写任何路径。gate 只拦常见写法（重定向、`rm`、`mv`、`sed -i`、`cp` 到 guardrail 路径等），拦不住所有写法 |
| 常见的危险终端命令：删根目录、`curl \| sh`、`git push` 等（拒绝或要人确认） | 子 agent 的调用也会触发 hook，但 hook 分不清是主 agent 还是子 agent。子 agent 的写入范围和主 agent 一样 |
| 同一个拒绝反复出现时，把拒绝理由换成"停止重试" | hook 只能拒绝，杀不掉一个一直重试的 agent。熔断靠那句话让它收尾 |
| 大小写、`..`、绝对路径、Windows 的 `\` 这些不同写法 | 间接写法，例如先 `cd` 进目录再用相对名字删除，或在脚本文件里写好再运行 |

需要更强的隔离，要用操作系统或容器层面的沙盒。gate 不是沙盒。
