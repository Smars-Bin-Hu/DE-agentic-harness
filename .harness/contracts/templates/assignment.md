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

- 成果和证据放在 `{outputs_dir}` 下，文件在它下面的位置，按它们将来在仓库里的相对路径放（例如 `{outputs_dir}/src/a.py`）。`handoff submit` 的 `--output`、`--evidence` 写相对于这个目录的路径（例如 `src/a.py`），不要写完整路径。子目录先用终端 `{mkdir}` 建好。
- 完成后运行 `{cli} handoff submit --request {request_id} --role {role} --status <passed|failed|blocked> --summary "<不超过几行>" ...`。
- 同一个工具调用被拒绝两次，就不再试，提交 `--status blocked` 并写明缺什么。
