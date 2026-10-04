# 快速开始

从克隆仓库到跑通第一个 L3 请求。

## 命令怎么写

下面的 `<cli>` 是运行 harness 命令的前缀：

| 系统        | `<cli>`                          |
| ----------- | ---------------------------------- |
| macOS/Linux | `python3 .harness/engine/cli.py` |
| Windows     | `python .harness/engine/cli.py`  |

在仓库根目录运行。装了短命令（见第 2 步）后，可以用 `harness` 代替 `<cli>`。

## 要求

- Python 3.9 或更新。macOS/Linux 用 `python3`，Windows 用 `python`。
- 只用标准库，不需要 `pip install`。
- git。用目标仓库时必须有。
- VS Code 和 GitHub Copilot Chat。`.vscode/settings.json` 里要开 `chat.useHooks`（仓库已经写好）。

## 1. 检查

```bash
<cli> doctor
```

最后一行 `{"errors": 0}` 就是通过。

- `[OK]` 正常。
- `[WARN]` 提醒，不影响运行（例如知识库没有 README）。
- `[ERROR]` 要先修。信息里写了哪个文件、哪一项。

## 2. 短命令（可选）

`.harness/bin/` 里有给人用的短命令：macOS/Linux 是 `harness`，Windows 是 `harness.cmd`。

```bash
.harness/bin/harness doctor
```

想在任何目录直接敲 `harness`，要做两件事：把它放进一个文件夹，再让这个文件夹在 PATH 里。

macOS/Linux（zsh；bash 把 `~/.zshrc` 换成 `~/.bashrc`）：

```bash
mkdir -p ~/bin
ln -sf "$PWD/.harness/bin/harness" ~/bin/harness
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
```

然后**重开终端**（或运行 `source ~/.zshrc`），再运行 `harness doctor`。提示 `command not found` 时，运行 `echo $PATH`，看 `~/bin` 在不在里面：只建链接不改 PATH 是最常见的原因。你的 PATH 里已经有别的自己的文件夹时（`echo $PATH` 能看到），把链接建在那里也行，不用再改 PATH。

Windows：把 `.harness\bin` 加进用户 PATH（系统设置里的“环境变量”），重开终端；或在 PowerShell 配置里加函数：`function harness { python C:\你的路径\.harness\engine\cli.py @args }`。

也可以只加 alias：`alias harness='python3 /你的路径/.harness/engine/cli.py'`。

这些都由你自己加，harness 不改你的环境变量。agent 的说明里写的仍是完整命令。

## 3. 选 Level

每个会话开始都是 L1。在提示开头写标记来切换：

| 标记                       | 含义                                                |
| -------------------------- | --------------------------------------------------- |
| `/l1`、`[L1]`          | 确定的小任务，直接做                                |
| `/l2`、`[L2]`          | 标准工程任务，先短计划；写`[verify]` 开启独立复核 |
| 选择`orchestrator` agent | L3：编排 builder 和 reviewer，见下一节              |

只有你能切换 Level，agent 只能建议。详细见 [核心功能](02-features.md)。

## 4. 配置目标仓库

要让 L3 改公司的代码仓库，先告诉 harness 仓库在哪。新建 `.harness/policies/target.override.json`（这个文件含你本机的路径，已被 git 忽略）：

```json
{ "repos_root": "/Users/你/repos" }
```

`repos_root` 下每个带 `.git` 的子文件夹就是一个目标仓库，名字是文件夹名。检查：

```bash
<cli> target list
```

更多写法见 [配置与定制](03-configure.md)。

## 5. 跑第一个 L3 请求

1. 在 `.workspace/current_tasks/<任务名>/REQ/` 放需求文件。
2. 在 Copilot Chat 里选 `orchestrator` agent，告诉它任务、任务目录和分支名（`feature/` 加字母、数字、下划线）。
3. orchestrator 自己建请求、取文件、派发 builder 和 reviewer。每一步的命令和判断见技能 [harness-orchestration](../.github/skills/harness-orchestration/SKILL.md)。
4. reviewer 通过后，orchestrator 运行 `promote --dry-run`，把计划给你看。你在**自己的终端**运行它给出的命令：

   ```bash
   <cli> request approve-promote --request <请求 id>
   ```

   看清文件和差异，输入屏幕上提示的确认码。
5. 你说“批准了”，orchestrator 运行 `promote`：在每个目标仓库新建分支，把成果写进去，**不提交**。成果和补丁另存在 `.workspace/current_tasks/<任务名>/DEV/`。
6. 你自己看差异、提交、建 PR。
7. 请求结束时报告写在 `.workspace/reports/<请求 id>.md`。

## 常见情况

- **工具调用被拒绝**：理由里写了原因和下一步。agent 会照做或停下来告诉你。
- **agent 要运行 git 写命令**：被拒绝，理由里有整条命令和验证码。你在自己的终端运行 `<cli> approve-command`，输入验证码，agent 再运行同一条命令（只放行一次）。
- **promote 中途出错**：请求进入 `partial`，信息里列出已写好、出错、没动的仓库。你在自己的终端运行 `<cli> request recover`，再让 agent 重新 `--dry-run`。
- **看用量和拒绝次数**：`<cli> stats`。
