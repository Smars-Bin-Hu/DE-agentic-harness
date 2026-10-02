# 智能体工作规则

本文件只放每个智能体都必须遵守的规则。仓库入口和文件索引见
[README.md](README.md)。具体规则放在对应的指令、技能或策略文件中。

## 核心开发定位

- 本仓库虽然使用 Claude Code 开发，但最终用户是 GitHub Copilot 用户。
  所有交付给用户的目录、文件和配置都必须使用 GitHub Copilot 支持的格式，
  不得为了兼容 Claude Code 而设计仓库结构。
- 本仓库只建设与 Knowledge Base 解耦的通用 AI agentic harness SDK。
  范围包括 agents、multi-agents、Hooks、通用 Skills、instructions、tools、
  权限、Task Level、sandbox 和 observability 等通用组件与能力。
- 本 SDK 用于帮助企业团队以轻量 harness 完成 SDLC。接入企业环境后，
  团队可以加入自己的 Knowledge Base、Skills 和其他定制内容，
  让 harness 直接执行团队任务。
- `knowledge-base/` 当前必须保持为空，只作为企业团队将来自定义的
  Knowledge Base 接入位置。不要在本仓库内预置、模拟或耦合具体业务知识。

## 文档语言

- 新建或修改文档时，只用中文。
- 代码、命令、路径、产品名，以及 Hooks、Skills、sandbox 等计算机或 AI
  领域的专业术语可以直接使用英文，无需强行翻译。
- 不要为了显得专业而加入英文。

## 文字要求

- 用短句和常用词。让 10 岁的小孩也能读懂。
- 内容要短、准、能执行。删掉没有实际信息的句子。
- 不用空洞、夸张或像广告的词。
- 不重复用户已经知道的内容，不写空洞的开场和总结。

## 信息放置

- 遵守渐进式披露：本文件只放核心规则和安全边界。
- README 是仓库的第一目录，只介绍仓库并指向具体文件。
- 详细规则放在 `.github/copilot-instructions.md`、`.github/instructions/`、
  `.github/skills/` 或 `.harness/policies/` 中。
- 一条规则只能有一个主要来源。其他文件只放链接和一句说明，不复制全文。
- 修改规则时，先找到主要来源。不要在多个指令文件或 `AGENTS.md`
  中生成大段相同内容。

## 核心边界

- 操作前先看真实文件。不要猜路径、命令、配置或测试方式。
- 保留用户已有的修改。不要改动无关文件。
- Task Level 只控制智能体的工作方式，不改变文件、网络、环境或生产权限。
- 使用最低够用的 Task Level。只有用户能切换 Level，你只能建议。
  L1 不用子智能体，L2 只在用户开启复核时用 verifier，只有 L3 做编排。
- 只有明确违反策略时，钩子才能阻止操作。钩子自身出错时不能误伤正常工作。
- 删除、覆盖或执行难以恢复的操作前，必须确认目标和范围。
