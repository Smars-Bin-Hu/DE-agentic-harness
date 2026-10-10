# 版本记录

每个版本改了什么。新的在上面。

每个版本分三栏：

- **新增**：新功能。
- **变更**：已有功能的行为变了。升级后要注意。
- **退役**：删掉的功能，和用什么代替。

查自己装的是哪一版：`harness --version`。

## 未发布

下一版要带的内容，合进主分支后先记在这里。发布时移到对应的版本号下面。

### 新增

暂无。

### 变更

暂无。

### 退役

暂无。

## 1.0.2（2026-10-10）

上手体验：短命令、版本图案、用户名字、初始化技能。

### 新增

- 技能 `/harness-repo-initialize`：带你做第一次配置。短命令、用户名字、目标仓库、知识库、公司技能，最后用 `doctor` 检查。
- `harness --version` 显示图案、版本、发布日期、作者。脚本里用 `harness --version --short`，只输出一行。
- `user.json` 策略和 `harness user` 命令：你的名字。agent 在要署名的地方用。写在 `user.override.json`，没写就用 `git config user.name`。
- `doctor` 检查短命令在不在 PATH 里，以及用户名字。
- Windows 上 PATH 只用改一次：往 PATH 里加一个固定的文件夹（例如 `C:\Users\<你>\bin`），把 `harness.cmd` 拷一份进去。以后升级放在哪都行，不用再改 PATH（公司电脑不用再找 helpdesk）。拷贝在仓库之外运行时读环境变量 `HARNESS_HOME`。`doctor` 认得这种拷贝，拷贝过期时给 `[WARN]`。

### 变更

- **短命令 `harness` 变成必须配置。** 文档、agent 收到的规则、拒绝理由里的命令都写成 `harness <命令>`，不再写 `python .harness/engine/cli.py <命令>`。升级后先把 `.harness/bin` 加进 PATH（见 [快速开始](01-quickstart.md) 第 1 步），否则 `doctor` 报错，agent 的命令会失败。
- `harness` 像 git 一样，操作当前目录所在的那一份仓库。电脑上有两份 harness 时不会再操作错。不在任何 harness 仓库里时，才用启动脚本自己所在的那一份。
- `harness --version` 以前输出一行，现在输出图案。脚本要一行的，改用 `harness --version --short`。
- agent 用短命令运行 `harness level set`、`harness logs prune` 现在也会被拦。以前只拦长命令的写法。

### 退役

暂无。

## 1.0.1（2026-10-10）

补丁：任务目录的写入范围、`DEV/` 根目录的文件、CLI 中文显示。

### 新增

- 任务目录里可以放不回写的成果。RCA、设计、笔记、一次性脚本写在任务目录根下，例如 `<任务>/RCA.md`，不需要计划和批准。
- `cli.json` 策略和 `output.encoding` 开关。CLI 的中文显示成 `\uXXXX` 时，在 `cli.override.json` 里设成 `utf-8`。
- `doctor` 多了“输出编码”几行：现在用什么编码、能不能显示中文。显示不了时，另打一行 UTF-8 样例，帮你判断开关该不该开。

### 变更

- L2 任务模式的写入范围变了。以前：批准计划前只能写 `PLAN.md`，批准后只能写 `DEV/`。现在：任务目录里都能写，只有 `DEV/` 要等计划批准。`REQ/`、`REF/` 不能写。任务目录之外仍然不能写。
- 直接放在 `DEV/` 根目录的文件不再挡住 `task promote`。它们不回写，计划和批准屏幕里会列出来。`DEV/<名字>/` 的名字不是已配置的仓库时仍然拒绝，防止仓库名写错。
- 写入被拒绝时，理由不再一律提 `task fetch`。只有直接改目标仓库的文件时才提。

### 退役

暂无。

## 1.0.0（2026-10-04）

第一个正式版本。在 macOS 和 Windows 上验证过。

### 新增

**三档 Task Level**

- L1 快答，L2 中等任务，L3 多 agent 协作。只有用户能切换：提示开头写 `/l2`、`[L2]`，或在下拉列表选 orchestrator。
- L1 的搜索有上限。L2 可以用 `[verify]` 打开独立复核（verifier）。

**gate（闸门）**

- guardrail 文件不能改。
- 危险的终端命令被拒绝，或要人确认。
- 目标仓库的工作区和任何 `.git` 文件夹不能直接写。
- git 写命令要人在终端批准；`push` 等永远拒绝。
- 同一个拒绝反复出现时，提示 agent 停止重试。

**目标仓库和 promote**

- 在 `target.override.json` 里配置代码仓库。agent 只能读。
- 从 main 取文件进工作区，改完后先 `--dry-run`，人在终端批准，再写到新分支。不提交。
- 支持新建、修改、删除文件，支持多个仓库。

**L2 任务模式**

- 一个 agent 做一个任务：写 `PLAN.md`，人在终端批准，只写任务目录的 `DEV/`，再 promote。
- 计划改了，批准失效。

**L3 多 agent 协作**

- orchestrator 调度，builder 做，reviewer 评审。在请求目录里工作。
- 计划要人批准才能开第一轮。评审不通过会返工，有轮数上限。

**admin 模式**

- 人在终端运行 `admin on`，这个会话可以改 guardrail 文件，用来二次开发 harness。

**日志、报告和检查**

- 每次工具调用和 gate 的决定都记进日志。`stats` 看统计，`logs prune` 清理。
- 请求和任务结束时写报告。
- `doctor` 自检配置。`eval check` 用固定场景检查行为。

**接入和定制**

- 用同名的 `.override.json` 改策略，不动默认文件。
- 知识库放进 `knowledge-base/`，`doctor` 会检查接入是否完整。
- 短命令 `harness`（macOS、Linux、Windows）。

**skill**

- `/generic-goal-driven`：把长任务拆成步骤，进度存成文件。
- `/generic-grill-me`：需求不清时先问清楚。
- `/generic-build-new-skill`：按模板新建 skill。

### 变更

无。这是第一个版本。

### 退役

无。
