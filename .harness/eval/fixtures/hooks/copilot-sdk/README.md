# Copilot SDK 引擎的 hook 真实输入（fixtures）

VS Code 1.140.0 里，Copilot 的 `@github/copilot` 1.0.89-7（SDK 引擎）发给 hook 的真实 stdin。2026-10-01 录制。
和 `../vscode/`（B1，旧引擎）不是同一种格式。已脱敏：用户目录、transcript 路径。`session_id` 换成固定名字。

## 目录

| 目录 | 内容 |
| --- | --- |
| `payloads/` | 每种事件、每种工具各一个样本。文件名是 `事件.工具名.json` |
| `sessions/` | 完整会话，每行一个 hook 输入，按到达顺序排列 |

| 会话 | 场景 |
| --- | --- |
| `cli-verifier-call.jsonl` | `[L2] [verify]` 提示：Bash、Write、调用 verifier（子 agent）、再 Bash。含子 agent 的独立会话 |
| `cli-tools-and-search-subagent.jsonl` | Edit、Grep、Glob、语义搜索（`search_code_subagent`，它自己再开一个子会话） |
| `cli-deny-top.jsonl` | 探针 hook 用顶层格式拒绝一条 Bash |
| `cli-stop-block.jsonl` | 探针 hook 用顶层格式 block 一次 Stop。第二条 UserPromptSubmit 就是 reason 原文，第二个 Stop 的 `stop_hook_active` 为 true |
| `cli-subagent-stop-block.jsonl` | 探针 hook 在 SubagentStop 上 block 一次：子会话收到 reason 作为新的 UserPromptSubmit，再 Stop，父会话收到第二个 SubagentStop |

## 和旧引擎的区别

| 项 | 旧引擎（`../vscode/`） | SDK 引擎 |
| --- | --- | --- |
| 工具名 | `run_in_terminal`、`read_file`、`create_file`、`replace_string_in_file`、`runSubagent` | `Bash`、`Read`、`Write`、`Edit`、`Grep`、`Glob`、`Agent`、`search_code_subagent` |
| 工具参数 | `command`、`filePath`、`agentName` | `Bash.command`；`Read/Write.path`（Write 内容在 `file_text`）；`Edit.path/old_str/new_str`；`Agent.name/agent_type/prompt/description/mode` |
| 工具结果 | `tool_response`（字符串） | `tool_result`：`{result_type, text_result_for_llm}` |
| `tool_use_id` | 有 | 没有 |
| SubagentStart | 有 `hook_event_name`、`agent_id` | **没有 `hook_event_name`**。camelCase：`sessionId`、`agentName`、`agentDescription`；时间戳是毫秒数 |
| 子 agent 的会话 | 和主 agent 同一个 `session_id` | **独立的 `session_id`**（verifier 是 UUID，`search_code_subagent` 是 `toolu_…`）。子会话没有 SessionStart |
| SubagentStop | `agent_id`、`agent_type` | 多 `agent_name`、`last_assistant_message`、`stop_reason`；`agent_id` 是子会话的 id |
| 事件顺序 | SessionStart 在 UserPromptSubmit 之前 | UserPromptSubmit 先，SessionStart 后（同一毫秒） |
| 输出格式 | deny、Stop block、SubagentStart 注入用 `hookSpecificOutput`（嵌套） | **顶层键**。嵌套的 `additionalContext`（UserPromptSubmit、PostToolUse）实测不送达；顶层的送达，PostToolUse 也送达 |

输出格式的实测结果：
- 顶层 `permissionDecision`/`permissionDecisionReason` 拒绝 Bash 有效，模型读到理由。
- UserPromptSubmit 顶层 `additionalContext` 送达，嵌套不送达。
- PostToolUse 顶层 `additionalContext` 送达（拼进工具结果），嵌套不送达。
- Stop 顶层 `decision: "block"` + `reason` **有效**。`reason` 会作为一条**新的 UserPromptSubmit**（`prompt` 就是 reason 原文）喂回模型；
  这条不是用户输入，核心用 `continuation` 标记识别，不重置本条提示的窗口。第二个 Stop 的 `stop_hook_active` 为 true。
- SubagentStart 顶层 `additionalContext` **有效**（verifier 的回答里出现了暗号）。
- SubagentStop 顶层 `decision: "block"` + `reason` **有效**：子 agent 继续工作，`reason` 作为子会话里的一条新 UserPromptSubmit 喂给它。
  所以子会话的后续 UserPromptSubmit 也不是用户输入，核心一律标记为 `from_subagent`。
- 内置的通用子 agent，`Agent` 的 `agent_type` 是 `explore`（来自拒绝理由；抓取脚本没抓到这次调用，因为同一事件上有 hook 已拒绝）。
- 模型会遵守注入的规则：L1 下被要求调用子 agent，它直接拒绝并建议用 `/l2`。

不要手改这些文件。平台升级后重新录制，再覆盖。
