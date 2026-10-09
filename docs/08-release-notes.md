# 版本记录

每个版本改了什么。新的在上面。

每个版本分三栏：

- **新增**：新功能。
- **变更**：已有功能的行为变了。升级后要注意。
- **退役**：删掉的功能，和用什么代替。

查自己装的是哪一版：`harness --version`。

## 未发布

下一版要带的内容，合进主分支后先记在这里。发布时移到对应的版本号下面。

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
