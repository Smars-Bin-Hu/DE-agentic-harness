# Task Level 参考

## 范围

Task Level 是任务级的执行策略。它控制自主程度、计划、探索范围、委派和软预算。
它从不授予或收回运行时、文件、网络、环境或生产权限。

每个新任务从 Level 1 开始。进行中的任务在后续提示里保持原 Level，直到被明确完成或替换。
完成后，下一个用户请求重新从 Level 1 开始。

## 三个 Level

具体数字只在 `.harness/policies/task-levels.json`。这里只写规则。

| Level | 适用 | 计划 | 探索 | 子 agent |
| --- | --- | --- | --- | --- |
| 1 | 确定、窄、有 SOP 的任务 | 不要 | 最少 | 禁止 |
| 2 | 相关文件间的有边界工程 | 建议，且要短 | 有限 | 禁止 |
| 3 | 跨系统、复杂 RCA、能并行的任务 | 必须 | 广 | 有次数上限 |

子 agent 的限制是硬的。搜索和工具次数是软预算：到 80% 提醒一次，不拒绝。

## 升级和降级

- L1 升 L2：窄任务需要找相关文件、写短计划，或有多个实现选择。
- L2 升 L3：只在跨子系统依赖、复杂 RCA，或独立工作确实值得委派时。
- 大范围调查把剩余工作缩小后，再降级。

每次切换都要写具体原因，并保留已有计数。state 里保存切换历史和最近完成或被替换的任务。

## 统计口径

- `observed_tool_calls`：hook 看得到的本地工具调用。
- `repository_searches`：`grep_search`、`file_search`、`semantic_search`，加终端里的 `rg`、`grep`、`git grep`、`find`。
- 工具名到类别的对应在 `.harness/engine/adapters/tool_kinds.json`。
- 绕开本地 hook 的托管工具不会被统计。读写文件、重试、迭代次数暂不统计。

## 配置

- hook 配置：`.github/hooks/harness.json`。所有事件都进 `.harness/engine/hook.py`。
- 会话 state：`.harness/runtime/state/<surface>/<session-id>.json`，不提交。
- 检查整套配置是否一致：`python3 .harness/engine/cli.py doctor`。
