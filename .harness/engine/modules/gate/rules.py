"""Texts the model sees when the gate refuses a call. Each says why it was refused and what to do next."""

from __future__ import annotations

from core.paths import cli_command


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


def git_folder(shown: str) -> str:
    return (
        f"`{shown}` 在 `.git` 文件夹里。任何 Level 都不能直接改 `.git`，改它会弄坏仓库的历史和配置。"
        "不要改它，也不要用终端命令绕过。需要提交或切分支时，停下来告诉用户。"
    )


def git_folder_terminal(why: str) -> str:
    return (
        f"这条终端命令会直接改 `.git` 文件夹或目标仓库不许写的路径（{why}）。"
        "不要换个命令重试。需要时，停下来告诉用户要做什么，由用户自己做。"
    )


def target_refused_file(repo: str, relative: str, pattern: str) -> str:
    return (
        f"`{repo}/{relative}` 属于目标仓库 {repo} 不许写的路径（{pattern}，见 target.json 的 refused_paths）。"
        "任何 Level 都不能改它。需要改它时，停下来告诉用户，由用户自己改。"
    )


def outside_request(relative: str, request_id: str, request_root: str) -> str:
    return (
        f"L3 请求 {request_id} 只能在 {request_root}/ 下写入，你要写的是 `{relative}`。"
        f"改成在 {request_root}/ 下写；要回写到仓库，用 promote（需要用户批准）。"
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


def cli_owned_file(relative: str) -> str:
    return (
        f"`{relative}` 由 CLI 生成和更新，不能直接写。"
        f"用 `{cli_command()}` 的命令来改它；没有对应的命令时，停下来告诉用户。"
    )


def cli_owned_terminal(why: str) -> str:
    return (
        f"这条终端命令会直接改由 CLI 生成的文件（{why}），例如 request.json、handoff.json、manifest.json。"
        f"用 `{cli_command()}` 的命令来改；没有对应的命令时，停下来告诉用户。"
    )


def git_never(why: str, command: str) -> str:
    return (
        f"这条 git 命令永远不能批准：{why}。命令：{command}\n"
        "不要换个写法重试。需要时，停下来告诉用户原因，由用户自己在终端运行。"
    )


def git_needs_approval(why: str, command: str, code: str, minutes: int) -> str:
    return (
        f"这条命令里的 git 命令会改仓库，agent 不能直接运行（{why}）。\n"
        f"命令：{command}\n"
        f"请把整条命令和验证码 {code} 告诉用户，让用户在自己的终端运行 `{cli_command()} approve-command`，看清命令后输入验证码。"
        f"用户批准后，{minutes} 分钟内可以把同一条命令再运行一次（只放行一次，写法要完全一样）。"
        "不要换个写法，也不要自己运行 approve-command。"
    )
