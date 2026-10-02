# 数据工程智能体框架

这个仓库用于管理 GitHub Copilot 的规则、技能、钩子和策略。仓库用 Claude Code 开发。
不同运行环境读取不同路径，下面的索引以仓库中的实际文件为准。
仓库现在没有业务代码，也没有通用的构建或发布命令。

README 是仓库的第一目录。先从这里找到目标文件，再读取需要的内容。
不要一次加载全部规则。

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
| [.harness/policies/agents.json](.harness/policies/agents.json)                                           | 模型系列：回退只能在同一系列，builder 和 reviewer 不同系列。 |
| [.harness/contracts/](.harness/contracts/)                                                               | L3 交接格式：request、manifest、handoff 的 schema 和 assignment 模板。 |
| [.harness/engine/hook.py](.harness/engine/hook.py)                                                       | hook 入口：识别运行时，分发给模块，合并结果。 |
| [.harness/engine/cli.py](.harness/engine/cli.py)                                                         | 命令入口：`doctor` 检查配置，`level` 管理 Level，`request` 等管理 L3 请求。 |
| [.harness/engine/modules/](.harness/engine/modules/)                                                     | 可插拔模块：`task_level`、`gate`、`request`。 |
| [.harness/engine/adapters/](.harness/engine/adapters/)                                                   | 运行时差异：payload 解析、输出格式、工具名表。 |
| [.harness/eval/fixtures/](.harness/eval/fixtures/)                                                       | 真实 hook 输入的录制样本，用于回放测试。     |
| [.harness/tests/](.harness/tests/)                                                                       | 全部测试。`python3 -m unittest discover -s .harness/tests` |
| [.workspace/README.md](.workspace/README.md)                                                             | 工作区目录约定，以及 gate 管得住和管不住什么。 |
| [knowledge-base/](knowledge-base/)                                                                       | 数据工程领域资料、术语、架构说明和操作手册。 |

## 本Harness Engineering核心组件

- Knowledge base (Context Engineering)
- Tools (MCP server + Local Custom Tool Calling)
- Skills
- Agents (multi-agents)
- Hooks
- .workspace
  - sandbox (任务执行的唯一路径)
  - current_tasks (for human use to store some tasks' files)
  - reports (for some tasks's execution report)
- .harness
  - Constitution (AGENTS.md, copilot-Instruction.md, *-instruction.md)
  - Decision Layer
  - Policies & Contract (对multi-agent协作，Skill 使用，Tool Calling 的contract)
  - Eval & Fixtures (结果评估和验收标准)
  - Observability （可观测性）
- .local
  - 本地存储，记录开发者的设计思想
  - 已知问题
  - 开发日志
