"""Texts the model sees when the gate refuses a call. Each says why it was refused and what to do next."""

from __future__ import annotations


def guardrail_file(relative: str, pattern: str) -> str:
    return (
        f"`{relative}` 是 guardrail 文件（{pattern}），所有 Level 都不能改。"
        "不要改它，也不要用终端命令绕过。需要改它时，停下来告诉用户要改什么，由用户自己改。"
    )


def guardrail_terminal(why: str) -> str:
    return (
        f"这条终端命令会改 guardrail 文件（{why}）。guardrail 文件所有 Level 都不能改。"
        "不要换个命令重试。需要改它时，停下来告诉用户要改什么，由用户自己改。"
    )


def outside_request(relative: str, request_id: str, request_root: str) -> str:
    return (
        f"L3 请求 {request_id} 只能在 {request_root}/ 下写入，你要写的是 `{relative}`。"
        f"改成在 {request_root}/ 下写；要回写到仓库，用 promote（需要人确认）。"
    )


def outside_repo_in_request(request_id: str, request_root: str) -> str:
    return (
        f"L3 请求 {request_id} 只能在 {request_root}/ 下写入，你要写的路径在仓库之外。"
        f"改成在 {request_root}/ 下写。"
    )


def bad_request_id(request_id: str) -> str:
    return f"L3 请求 id `{request_id}` 不合法，无法确定可写目录，所有写入都被拒绝。停下来告诉用户。"


def terminal_denied(why: str) -> str:
    return f"这条终端命令被拒绝：{why}。不要重试同类命令。需要时，停下来告诉用户原因，由用户自己运行。"


def terminal_ask(why: str) -> str:
    return f"这条终端命令{why}，需要用户确认。"
