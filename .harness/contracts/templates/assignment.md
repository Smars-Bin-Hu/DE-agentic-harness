# 任务：{role}，第 {attempt} 轮

请求：{request_id}

## 目标

（待填）

## 验收标准

（待填）

## 先读什么

1. 先读 `manifest.json` 列出的文件，尤其是它的 `brief`（知识简报）。manifest 里的 `brief_delta` 是这一轮新增或改动的条目。
2. brief 不够再查知识库。查到的写进 handoff 的 `--kb-addition`（来源 :: 一句话结论）。
3. skills、指令、知识库都可以读。

## 怎么交

- 成果和证据放在 `{outputs_dir}` 下，路径按仓库相对路径写。目录先用终端 `mkdir -p` 建好。
- 完成后运行 `python3 .harness/engine/cli.py handoff submit --request {request_id} --role {role} --status <passed|failed|blocked> --summary "<不超过几行>" ...`。
- 同一个工具调用被拒绝两次，就不再试，提交 `--status blocked` 并写明缺什么。
