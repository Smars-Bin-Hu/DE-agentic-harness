# GitHub Copilot Agentic Harness for DE Team

Copilot 很会写代码，但在企业里用 VS Code 做复杂任务时，常有这些麻烦：

- **规则只是请求**：写在提示词里的规则，模型可以不照做。它会改到不该改的文件、跑危险命令，或者直接动 `.git`。
- **多 agent 流程每次不一样**：让它自己调子 agent，可能跳过评审、自己评自己；状态只在对话里，上下文一压缩就丢。
- **说“完成”没有证据**：改了什么、谁评审过、为什么返工，事后很难查。
- **确认弹窗靠不住**：“Allow in this Session”点一次就关掉了，等于没有确认。
- **改企业的代码仓库有风险**：文件多、不能整个复制；回写时可能误提交、误推送。
- **成本不好控**：小任务也走重流程，上下文被整文件和长回复占满。

这个 harness 的做法：

- **用代码强制规则**：hook 和命令行在每次工具调用前检查，越界写、`.git`、危险命令直接拒绝。说明只负责教模型，不负责拦。
- **按任务大小选做法**：L1、L2、L3 三档，由你切换。小任务不走重流程。
- **把多 agent 流程固定下来**：orchestrator、builder、reviewer 分工。输入冻结、交接留文件、没有评审通过不能回写，上下文丢了也能续做。
- **关键动作由人批准**：回写仓库、git 写命令，要你在自己的终端里确认；`push` 这类永远不能批准。
- **安全地改企业仓库**：只取要改的文件，改完写到新分支且不提交，留有备份和恢复命令。
- **看得见、能复盘**：每个会话有日志，每个请求有报告，固定场景可以重复检查。
- **省时间和钱**：命令代替模型做确定的事，只读需要的、只写必要的，子 agent 只回一行。

它和知识库解耦：接入你们自己的知识库、技能和代码仓库，就能按这套流程做团队的日常任务。

给 agent：[AGENTS.md](AGENTS.md) 已自动加载。需要找文件时，只读下面的“路径索引”一节。不要通读本文件，不要读 `docs/`。

## 文档

从上往下读，或者直接跳到你要的那一篇。

| 文档 | 你会看到什么 |
| --- | --- |
| [docs/01-quickstart.md](docs/01-quickstart.md) | **想马上跑起来**：环境要求（Python 3.9+，不用 `pip install`）、`doctor` 自检、`harness` 短命令、配置目标仓库、跑通第一个 L2 任务和第一个 L3 请求 |
| [docs/02-features.md](docs/02-features.md) | **它到底能做什么**：三档 Level 按任务大小选做法；gate 拦住越界写和危险命令；L2 任务模式（一个 agent，计划和回写都由你批准）；orchestrator、builder、reviewer 多 agent 协作；人批准的 promote 和 git 命令；日志、统计、报告 |
| [docs/03-configure.md](docs/03-configure.md) | **接入你们自己的东西**：用 override 改配置而不动默认值，配置目标仓库，接入知识库和 domain 技能，给每个角色选模型 |
| [docs/04-reference.md](docs/04-reference.md) | **查表用**：全部命令和常用命令、策略字段、交接格式、hook 事件、运行时文件 |
| [docs/05-design.md](docs/05-design.md) | **为什么这样设计**：组件怎么分层，L1、L2、L3 是什么，哪些事交给代码、哪些交给模型 |
| [docs/06-cost-optimization.md](docs/06-cost-optimization.md) | **怎么省时间和钱**：按任务大小选做法，只读需要的、只写必要的，早失败、能续做，以及哪里仍然会贵 |
| [docs/07-prompts.md](docs/07-prompts.md) | **直接复制的提示**：L1、L2、L2 任务模式、L3 各一份模板，写清需求、目标仓库、知识库和在哪一步停下等你批准 |

## 必须接入的部分

harness 本身是通用的，不带任何业务内容。**下面两样不接入，它没法面向你们的日常需求工作**：

- **企业知识库**：把知识库放进 `knowledge-base/`，同时把知识库**自带的 instructions** 放到 [.github/instructions/knowledgebase.instructions.md](.github/instructions/knowledgebase.instructions.md)。这个文件交付时是空的占位：它是知识库的一个组件，没有它，agent 不知道怎么按索引读知识库。`doctor` 会提醒。接入方法见 [配置与定制](docs/03-configure.md)。
- **目标仓库**：在 `target.override.json` 里写 `repos_root`，指向放着你们代码仓库的文件夹。harness 面向的是没有入口、不能在本机运行的数据工程 pipeline 代码库（按 domain 或功能存放大量 Python、SQL、`.json`、`.sh`、PowerShell 文件）。没配置时，agent 改不了你们的代码。配置后，目标仓库只能经你批准的 promote 写入（L2 任务模式和 L3 都是）。

## 目录结构

分两部分：harness 本身（含知识库的接入位置），和 harness 之外的目标仓库。

```text
本仓库（harness）
├── AGENTS.md                      所有 agent 都要遵守的核心规则
├── README.md、docs/               说明文档
├── .github/
│   ├── copilot-instructions.md    仓库级规则
│   ├── instructions/              分类规则；其中 knowledgebase.instructions.md 是企业知识库的一部分，必须接入（交付时为空）
│   ├── skills/                    技能：harness-*、generic-*（企业自己加 domain-*）
│   ├── agents/                    orchestrator、builder、reviewer、verifier
│   └── hooks/harness.json         hook 配置
├── .harness/
│   ├── engine/                    hook 和命令行（引擎）
│   ├── policies/                  策略；企业用 *.override.json 覆盖，目标仓库在 target.override.json 里配
│   ├── contracts/、eval/、tests/  交接格式、固定场景、测试
│   ├── bin/                       短命令 harness、harness.cmd
│   └── runtime/                   状态和日志（不进 git）
├── .workspace/
│   ├── current_tasks/<任务>/      人放任务材料（REQ、REF、TEST）；L2 任务的 PLAN.md 和成果 DEV/；L3 promote 的备份也写进 DEV
│   ├── sandbox/requests/<id>/     L3 请求的执行目录（不进 git）
│   └── reports/                   请求报告（不进 git）
└── knowledge-base/                企业知识库的接入位置（交付时为空）

harness 之外：目标仓库（企业的代码仓库）
<repos_root>/                      在 target.override.json 里配置的文件夹
├── bdtt_repo/                     每个带 .git 的子文件夹是一个目标仓库
└── b9td_repo/                     harness 只读它们的 main；promote 经人批准后才写到新分支
```

## 路径索引

| 路径 | 用途 |
| --- | --- |
| [AGENTS.md](AGENTS.md)、[.github/copilot-instructions.md](.github/copilot-instructions.md) | 核心规则和安全边界；仓库级规则 |
| [.github/instructions/](.github/instructions/) | 分类规则：[agents](.github/instructions/agents.instructions.md)、[skills](.github/instructions/skills.instructions.md)、[tools](.github/instructions/tools.instructions.md)、[workspace](.github/instructions/workspace.instructions.md)（`.workspace/` 的读写规则） |
| [.github/skills/harness-task-level/](.github/skills/harness-task-level/)、[.github/skills/harness-orchestration/](.github/skills/harness-orchestration/) | Task Level 的使用流程和 L2 任务模式的每一步；L3 请求的每一步用哪条命令 |
| [.github/skills/generic-goal-driven/](.github/skills/generic-goal-driven/) | 长周期任务的目标驱动流程：中心思想、TODO、进度指针存成文件，换 session 能接上。只由用户用 `/generic-goal-driven` 启动 |
| [.github/agents/](.github/agents/) | 自定义智能体：orchestrator、admin（用户可选）、builder、reviewer、verifier。admin 用来二开和排查 harness，要先在终端开 admin 模式 |
| [.github/hooks/harness.json](.github/hooks/harness.json) | 唯一的 hook 配置，所有事件进同一个入口 |
| [.harness/registry.json](.harness/registry.json) | 模块注册表：开关、订阅的事件、文件清单 |
| [.harness/policies/](.harness/policies/) | 策略：task-levels、gate、orchestration、observe、agents、target。覆盖写在同名 `.override.json`，规则见 [配置与定制](docs/03-configure.md) |
| [.harness/contracts/](.harness/contracts/) | L3 交接格式：request、manifest、handoff 的 schema 和 assignment 模板 |
| [.harness/engine/](.harness/engine/) | [hook.py](.harness/engine/hook.py)（hook 入口）、[cli.py](.harness/engine/cli.py)（命令入口）、modules/（task_level、gate、request、observe、evalcheck）、adapters/（运行时差异） |
| [.harness/bin/](.harness/bin/) | 给人用的短命令：`harness`（macOS/Linux）、`harness.cmd`（Windows） |
| [.harness/eval/](.harness/eval/) | 固定场景（scenarios/）和真实 hook 输入的录制样本（fixtures/） |
| [.harness/tests/](.harness/tests/) | 全部测试：`<cli>` 换成 `python -m unittest discover -s .harness/tests`（macOS/Linux 用 `python3`） |
| [.workspace/README.md](.workspace/README.md) | 工作区目录约定，以及 gate 管得住和管不住什么 |
| [knowledge-base/](knowledge-base/) | 接入企业知识库的位置，交付时为空 |
