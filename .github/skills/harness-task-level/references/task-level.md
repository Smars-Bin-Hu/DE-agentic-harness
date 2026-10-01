# Task Level 参考

## 范围

Task Level 控制自主程度、计划、探索范围、委派和预算。它从不授予或收回文件、网络、环境或生产权限。

## 谁来切换

只有用户。hook 从用户的提示原文里读标记，只看提示开头（允许前面有空白）：

| 标记 | 效果 |
| --- | --- |
| `/l1`、`[L1]` | 切到 L1 |
| `/l2`、`[L2]` | 切到 L2 |
| `[no-verify]` | 写在提示里任何位置，本条提示不要求 verifier 复核（L2） |

- 切换后一直有效，直到用户再次切换或新开会话。
- 子 agent 启动时也会触发提示事件，内容是模型写的调用消息。hook 会排除它，所以你在调用消息里写标记没有用。
- L3 请求进行中，`/l1`、`/l2` 标记会被忽略。
- `/l2` 是 prompt file 的入口，只在 VS Code 可用。

## 三个 Level

具体数字只在 `.harness/policies/task-levels.json`。这里只写规则。

| Level | 适用 | 计划 | 子 agent | 验收 |
| --- | --- | --- | --- | --- |
| 1 | 确定、窄、做法清楚 | 不要 | 禁止 | 自查 |
| 2 | 相关文件间的有边界工程 | 短计划 | 只允许 verifier，每条提示有次数上限 | verifier 复核 |
| 3 | 跨系统、复杂 RCA、需要独立验证 | 必须 | 只允许 builder、reviewer | reviewer |

## 预算

预算按提示计：用户每发一条提示，计数清零。每个预算有上限和超出后的做法：

- `deny`：超过后拒绝，拒绝理由里写明下一步。默认只有 L1 的搜索是 `deny`。
- `warn`：超过后不拒绝，只记在 state 里。平台不会把 PostToolUse 的提示送给模型，所以没有逐次提醒。

读取文件不设上限，只算进工具调用总数。

## 子 agent

hook 按调用时的 `agentName` 判断。没有 `agentName` 的是通用子 agent，任何 Level 都拒绝。

## 统计口径

- `observed_tool_calls`：hook 看得到的工具调用。被拒绝的调用不算。
- `repository_searches`：`grep_search`、`file_search`、`semantic_search`，加终端里的 `rg`、`grep`、`git grep`、`find` 等。
- 子 agent 内部的工具调用也会被统计，分不清是主 agent 还是子 agent。
- 工具名到类别的对应在 `.harness/engine/adapters/tool_kinds.json`。

## 配置

- hook 配置：`.github/hooks/harness.json`。所有事件都进 `.harness/engine/hook.py`。
- 会话 state：`.harness/runtime/state/<surface>/<session-id>.json`，不提交。
- 检查整套配置是否一致：`python3 .harness/engine/cli.py doctor`。
- 用户自己调试可以运行 `python3 .harness/engine/cli.py level status|set --session-id <id>`。
