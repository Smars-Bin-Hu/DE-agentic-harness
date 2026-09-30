# VS Code hook 真实输入（fixtures）

这些是 VS Code Copilot agent mode 里，hook 收到的真实 stdin（2026-09-30 录制，Copilot Chat 0.68.0，VS Code 1.140.0）。
已脱敏：用户目录、主机名、transcript 路径。`session_id` 已换成固定名字。

## 目录

| 目录 | 内容 |
| --- | --- |
| `payloads/` | 每种事件、每种工具各一个样本，文件名是 `事件.工具名.json` |
| `sessions/` | 完整会话。每行一个 hook 输入，按到达顺序排列 |

## 会话

| 文件 | 场景 |
| --- | --- |
| `tools-basic.jsonl` | 读文件、创建文件、终端命令、搜索 |
| `tools-edit-list-search.jsonl` | 编辑文件、列目录、按文件名搜索、语义搜索 |
| `prompt-l2-marker.jsonl` | 提示以 `[L2]` 开头。提示被粘贴时带了 markdown 代码围栏，这是粘贴造成的，解析标记时要允许开头有空白 |
| `subagent-child.jsonl` | 默认 agent 调用子 agent。含 SubagentStart/Stop 和子 agent 触发的 UserPromptSubmit |
| `subagent-default-to-locked.jsonl` | 默认 agent 调用带 `disable-model-invocation: true` 的 agent，调用成功 |
| `stop-block-once.jsonl` | Stop 被 block 一次后，第二个 Stop 的 `stop_hook_active` 为 true |

## 这些数据证明的事实

- 字段全是 snake_case。公共字段：`timestamp`、`cwd`、`session_id`、`hook_event_name`、`transcript_path`。
- 工具名：`read_file`、`create_file`、`replace_string_in_file`、`list_dir`、`file_search`、`grep_search`、`semantic_search`、`run_in_terminal`、`runSubagent`。
- 子 agent 的目标名在 `PreToolUse` 的 `tool_input.agentName`。
- 子 agent 启动会再触发一次 `UserPromptSubmit`，内容是调用消息。子 agent 内部的工具事件没有 agent 标记，`session_id` 和主 agent 相同。
- `SubagentStop` 和 `Stop` 触发时，transcript 里最后一条 `assistant.message` 已经写完。

## 用法

- 离线回放：逐行读 jsonl，按 `hook_event_name` 送给 hook。
- 不要手改这些文件。平台升级后重新录制，再覆盖。
