# 数据工程智能体框架

这个仓库是给 GitHub Copilot 用的轻量 harness：用 hook 和命令行强制关键规则，用 agents、skills 和 instructions 指导模型做事。
它和知识库解耦。企业接入自己的知识库、技能和目标仓库后，就能让 Copilot 按这套流程执行团队任务。

README 是仓库的第一目录，只介绍和指路。先从这里找到目标文件，再读需要的内容，不要一次加载全部规则。

## 它做什么

- **Task Level**：L1、L2、L3 三种工作方式，由用户切换。
- **gate**：拦截改 guardrail 文件、L3 越界写、`.git` 和危险终端命令。
- **L3 多 agent 协作**：orchestrator 调度 builder 和 reviewer，输入、交接、返工都留在请求目录里。
- **目标仓库**：从各仓库的 main 取要改的文件，人批准后写到新分支，不提交。
- **git 批准**：agent 的 git 写命令要人在终端批准，`push` 等永远不能批准。
- **可观测**：会话日志、统计、请求报告、固定场景检查。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/01-quickstart.md](docs/01-quickstart.md) | 快速开始：检查、短命令、配置目标仓库、跑第一个 L3 请求 |
| [docs/02-features.md](docs/02-features.md) | 核心功能：Level、gate、L3 请求、目标仓库、git 批准、可观测 |
| [docs/03-configure.md](docs/03-configure.md) | 配置与定制：override、目标仓库、知识库、技能、模型 |
| [docs/04-reference.md](docs/04-reference.md) | 命令与字段参考：命令、策略字段、交接格式、hook 事件、运行时文件 |
| [docs/05-design.md](docs/05-design.md) | 设计思想：为什么这样做 |

## 开始之前

- Python 3.9 或更新。只用标准库，不需要 `pip install`。
- macOS/Linux 用 `python3`，Windows 用 `python`。
- 第一条命令：`<cli> doctor`（`<cli>` 在 macOS/Linux 是 `python3 .harness/engine/cli.py`，Windows 是 `python .harness/engine/cli.py`），最后一行 `{"errors": 0}` 就是配置一致。
- 短命令：`.harness/bin/harness doctor`。怎么放进 PATH 见 [快速开始](docs/01-quickstart.md)。

## 阅读顺序

1. 先读 [AGENTS.md](AGENTS.md)，了解所有任务都要遵守的短规则。
2. 在下面的索引中找到与任务有关的文件。
3. 只读取需要的指令、技能、策略或测试。

## 路径索引

| 路径                                                                                                  | 用途                                         |
| ----------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| [AGENTS.md](AGENTS.md)                                                                                   | 所有智能体都要遵守的核心规则和安全边界。     |
| [.github/copilot-instructions.md](.github/copilot-instructions.md)                                       | GitHub Copilot 的仓库级规则。                |
| [.github/instructions/](.github/instructions/)                                                           | 按文件类型或任务范围加载的细分规则。         |
| [.github/instructions/agents.instructions.md](.github/instructions/agents.instructions.md)               | 智能体文件的编写规则。                       |
| [.github/instructions/skills.instructions.md](.github/instructions/skills.instructions.md)               | 技能文件的编写规则。                         |
| [.github/instructions/tools.instructions.md](.github/instructions/tools.instructions.md)                 | 工具配置的编写规则。                         |
| [.github/instructions/knowledgebase.instructions.md](.github/instructions/knowledgebase.instructions.md) | 知识库文件的编写规则。                       |
| [.github/instructions/workspace.instructions.md](.github/instructions/workspace.instructions.md)         | 在 `.workspace/` 里读写的规则。              |
| [.github/skills/](.github/skills/)                                                                       | 可重复使用的任务流程和参考资料。             |
| [.github/agents/](.github/agents/)                                                                       | 自定义智能体：orchestrator（用户可选）、builder、reviewer、verifier。 |
| [.github/skills/harness-task-level/](.github/skills/harness-task-level/)                                 | Task Level 的使用流程和参考。                |
| [.github/skills/harness-orchestration/](.github/skills/harness-orchestration/)                           | L3 请求的完整流程：orchestrator 每一步用哪条命令。 |
| [.github/hooks/harness.json](.github/hooks/harness.json)                                                 | 唯一的 hook 配置。所有事件进同一个入口。     |
| [.harness/registry.json](.harness/registry.json)                                                         | 模块注册表：开关、订阅的事件、文件清单。     |
| [.harness/policies/task-levels.json](.harness/policies/task-levels.json)                                 | Task Level 1、2、3 的机器可读规则。          |
| [.harness/policies/gate.json](.harness/policies/gate.json)                                               | 闸门规则：guardrail 文件、L3 写入范围、危险命令、熔断。 |
| [.harness/policies/orchestration.json](.harness/policies/orchestration.json)                               | L3 请求的上限：轮数、brief 大小、handoff 摘要行数。 |
| [.harness/policies/observe.json](.harness/policies/observe.json)                                         | 日志：每个会话一个文件，记录多长的文字，capture 开关。 |
| [.harness/policies/agents.json](.harness/policies/agents.json)                                           | 模型系列：回退只能在同一系列，builder 和 reviewer 不同系列。 |
| `.harness/policies/<名>.override.json`                                                                     | 企业覆盖：只写要改的项。对象逐项合并，数组整体替换，`"<键>+": [...]` 表示追加。`doctor` 列出改了哪些项，核心 guardrail 删不掉。 |
| [.harness/contracts/](.harness/contracts/)                                                               | L3 交接格式：request、manifest、handoff 的 schema 和 assignment 模板。 |
| [.harness/engine/hook.py](.harness/engine/hook.py)                                                       | hook 入口：识别运行时，分发给模块，合并结果。 |
| [.harness/engine/cli.py](.harness/engine/cli.py)                                                         | 命令入口。命令清单见下面的“常用命令”。 |
| [.harness/bin/](.harness/bin/)                                                                           | 给人用的短命令：`harness`（macOS/Linux）、`harness.cmd`（Windows）。 |
| [.harness/engine/modules/](.harness/engine/modules/)                                                     | 可插拔模块：`task_level`、`gate`、`request`、`observe`、`evalcheck`。 |
| [.harness/engine/adapters/](.harness/engine/adapters/)                                                   | 运行时差异：payload 解析、输出格式、工具名表。 |
| [.harness/eval/scenarios/](.harness/eval/scenarios/)                                                     | 固定场景：`scenario.md`（怎么跑、人看什么）和 `expect.json`（程序检查什么）。 |
| [.harness/eval/fixtures/](.harness/eval/fixtures/)                                                       | 真实 hook 输入的录制样本，用于回放测试。     |
| [.harness/tests/](.harness/tests/)                                                                       | 全部测试。`python -m unittest discover -s .harness/tests`（macOS/Linux 用 `python3`） |
| [.workspace/README.md](.workspace/README.md)                                                             | 工作区目录约定，以及 gate 管得住和管不住什么。 |
| [knowledge-base/](knowledge-base/)                                                                       | 接入企业知识库的位置。交付时为空。           |
| [docs/](docs/)                                                                                           | 使用文档：快速开始、核心功能、配置与定制、命令与字段参考、设计思想。 |

## 常用命令

`<cli>` 在 macOS/Linux 是 `python3 .harness/engine/cli.py`，Windows 是 `python .harness/engine/cli.py`，也可以用短命令 `harness`。每条命令的全部参数用 `--help` 看。

| 命令 | 作用 |
| --- | --- |
| `<cli> doctor` | 检查配置是否一致 |
| `<cli> level status`、`level set` | 看或设 Level（只有用户能设） |
| `<cli> target list` | 列出目标仓库 |
| `<cli> request list`、`request show` | 看请求 |
| `<cli> request approve-promote` | 批准回写（用户在终端运行） |
| `<cli> request recover` | promote 中途出错后恢复（用户在终端运行） |
| `<cli> approve-command` | 批准 agent 被拒绝的 git 命令（用户在终端运行） |
| `<cli> report` | 重写请求报告 |
| `<cli> stats`、`logs prune` | 看日志汇总、清理旧日志 |
| `<cli> eval list`、`eval show`、`eval check` | 固定场景 |

其他命令（`request new`、`dispatch`、`handoff submit`、`promote` 等）由 orchestrator、builder、reviewer 使用，见 [命令与字段参考](docs/04-reference.md)。

## 目录

- `AGENTS.md`、`.github/`：规则、指令、技能、agent、hook 配置。
- `.harness/`：引擎（hook 和命令行）、策略、交接格式、固定场景、测试。
- `.workspace/`：工作区。`sandbox/` 是 L3 执行的唯一路径，`current_tasks/` 放人的任务材料，`reports/` 放请求报告。运行内容不进 git。
- `knowledge-base/`：企业知识库的接入位置。
- `docs/`：使用文档。
