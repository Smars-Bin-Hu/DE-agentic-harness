# 快速开始

从克隆仓库到跑通第一个 L2 任务和第一个 L3 请求。可以直接复制的提示见 [提示模板](07-prompts.md)。

## 要求

- Python 3.9 或更新。macOS/Linux 用 `python3`，Windows 用 `python`。
- 只用标准库，不需要 `pip install`。
- git。用目标仓库时必须有。
- VS Code 和 GitHub Copilot Chat。`.vscode/settings.json` 里要开 `chat.useHooks`（仓库已经写好）。

## 1. 短命令（必须）

所有命令都写成 `harness <命令>`：文档里、agent 收到的规则里、拒绝理由里都是。所以要先让终端认得 `harness`。只做一次。

想让 agent 带着你做：在 Copilot 对话里输入 `/harness-repo-initialize`。下面是手动的做法。

启动脚本在 `.harness/bin/`：macOS/Linux 是 `harness`，Windows 是 `harness.cmd`。要做的事只有一件：让它在 PATH 里。

macOS/Linux（zsh；bash 把 `~/.zshrc` 换成 `~/.bashrc`），在仓库根目录运行：

```bash
mkdir -p ~/bin
ln -sf "$PWD/.harness/bin/harness" ~/bin/harness
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
```

你的 PATH 里已经有自己的文件夹时（`echo $PATH` 能看到），把链接建在那里就行，不用再改 PATH。

Windows：用一个**固定的文件夹**，PATH 只改这一次，以后升级不用再改。

1. 建一个仓库之外的文件夹，例如 `C:\Users\<你>\bin`。
2. 把 `.harness\bin\harness.cmd` **拷**一份进去（拷贝，不用链接：Windows 的链接要管理员权限）。
3. 把这个文件夹加进用户 PATH（系统设置里搜“环境变量”，编辑用户变量 `Path`，新建一行，填完整路径）。
   公司电脑不让自己改的话，请 helpdesk 远程加这一条：“请把 `C:\Users\<你>\bin` 加进我账户的 Path”。

以后下载新版本，放在哪都行。`harness` 按当前目录找仓库，进到哪一份就用哪一份。脚本本身变了时，`doctor` 会给 `[WARN]`，你再拷一份，不用找 helpdesk。

然后**重开终端，也重开 VS Code**。Copilot 的终端用的是 VS Code 启动时的 PATH，不重开它认不到。

- `harness` 像 git 一样，操作的是**当前目录所在的那一份** harness 仓库。电脑上有两份仓库时，在哪一份里运行，就操作哪一份。不在任何 harness 仓库里时，用启动脚本自己所在的那一份；固定文件夹里的拷贝没有自己的仓库，这时读环境变量 `HARNESS_HOME`（设成某份仓库的路径），没设就报“不在 harness 仓库里”。
- 提示 `command not found` 时，运行 `echo $PATH`，看 `~/bin` 在不在里面：只建链接不改 PATH 是最常见的原因。
- 不要用 alias 或 PowerShell 函数代替。它们只在你自己的交互式终端里有效，agent 的终端里没有。
- 这一步由你自己做。harness 和 agent 都不改你的环境变量。

## 2. 检查

```bash
harness doctor
```

最后一行 `{"errors": 0}` 就是通过。

- `[OK]` 正常。
- `[WARN]` 提醒，不影响运行（例如知识库没有 README）。
- `[ERROR]` 要先修。信息里写了哪个文件、哪一项。

第 1 步没做好时，`harness` 本身运行不了。这时用完整路径运行一次，看它怎么说：macOS/Linux 是 `.harness/bin/harness doctor`，Windows 是 `.harness\bin\harness.cmd doctor`。

## 3. 选 Level

每个会话开始都是 L1。在提示开头写标记来切换：

| 标记                       | 含义                                                |
| -------------------------- | --------------------------------------------------- |
| `/l1`、`[L1]`          | 确定的小任务，直接做                                |
| `/l2`、`[L2]`          | 标准工程任务，先短计划；写`[verify]` 开启独立复核。指定任务目录并要改文件时，走任务模式（第 5 节） |
| 选择`orchestrator` agent | L3：编排 builder 和 reviewer，见下一节              |

只有你能切换 Level，agent 只能建议。详细见 [核心功能](02-features.md)。

## 4. 配置目标仓库

要让 agent 改公司的代码仓库，先告诉 harness 仓库在哪。新建 `.harness/policies/target.override.json`（这个文件含你本机的路径，已被 git 忽略）：

```json
{ "repos_root": "/Users/你/repos" }
```

`repos_root` 下每个带 `.git` 的子文件夹就是一个目标仓库，名字是文件夹名。检查：

```bash
harness target list
```

更多写法见 [配置与定制](03-configure.md)。

## 5. 跑第一个 L2 任务

日常的开发任务用它：一个 agent，你批准计划，你批准回写。

1. 在 `.workspace/current_tasks/<任务名>/REQ/` 放需求文件（参考代码放 `REF/`）。
2. 在 Copilot Chat 里用默认 agent，提示开头写 `/l2`，说清任务目录、目标仓库、知识库在哪（模板见 [提示模板](07-prompts.md)）。
3. agent 运行 `task start`，读需求和知识库，把计划写到 `<任务>/PLAN.md`，然后停下来，给你文件的链接。
4. 你在编辑器里看计划。同意就在**自己的终端**运行：

   ```bash
   harness task approve-plan
   ```

   输入屏幕上的确认码。要改计划，直接告诉 agent，改完再批准。
5. 你说“批准了”。agent 用 `task fetch` 把要改的文件取到 `<任务>/DEV/<仓库名>/<路径>`，在那里改。它只能写任务目录；不回写的东西（RCA、一次性脚本）放任务目录根下。
6. 写了 `[verify]` 的话，verifier 读差异做一次独立复核。任务里写一次就够，后面的“计划批准了”“批准了”不用再写。
7. agent 运行 `task promote --dry-run`，给你 `PROMOTE-PLAN.diff` 的链接。你在编辑器里看差异，同意就运行：

   ```bash
   harness task approve-promote
   ```

8. 你说“批准了”，agent 运行 `task promote`：在每个目标仓库从 main 新建分支 `feature/<任务名>`，把文件写进去，**不提交**。
9. `task close` 后报告在 `.workspace/reports/task-<任务名>.md`。

只是问答、RCA、出方案，不改文件时，不用任务目录，照常用 `/l2` 提问就行。

## 6. 跑第一个 L3 请求

1. 在 `.workspace/current_tasks/<任务名>/REQ/` 放需求文件。
2. 在 Copilot Chat 里选 `orchestrator` agent，告诉它任务、任务目录和分支名（`feature/` 加字母、数字、下划线）。
3. orchestrator 自己建请求、取文件、写计划。它停下来给你 `plan.md` 的链接。你在编辑器里看，同意就在**自己的终端**运行：

   ```bash
   harness request approve-plan --request <请求 id>
   ```

4. 你说“批准了”，orchestrator 派发 builder 和 reviewer。每一步的命令和判断见技能 [harness-orchestration](../.github/skills/harness-orchestration/SKILL.md)。
5. reviewer 通过后，orchestrator 运行 `promote --dry-run`，给你 `promote-plan.diff` 的链接。你在编辑器里看差异，同意就运行它给出的命令：

   ```bash
   harness request approve-promote --request <请求 id>
   ```

   输入屏幕上提示的确认码。
6. 你说“批准了”，orchestrator 运行 `promote`：在每个目标仓库新建分支，把成果写进去，**不提交**。成果和补丁另存在 `.workspace/current_tasks/<任务名>/DEV/`。
7. 你自己看差异、提交、建 PR。
8. 请求结束时报告写在 `.workspace/reports/<请求 id>.md`。

## 常见情况

- **工具调用被拒绝**：理由里写了原因和下一步。agent 会照做或停下来告诉你。
- **agent 要运行 git 写命令**：被拒绝，理由里有整条命令和验证码。你在自己的终端运行 `harness approve-command`，输入验证码，agent 再运行同一条命令（只放行一次）。
- **agent 想直接改目标仓库的文件**：被拒绝。目标仓库只有 promote 能写。L2 用任务模式，L3 用请求。
- **promote 中途出错**：进入 `partial`，信息里列出已写好、出错、没动的仓库。你在自己的终端运行 `harness request recover`（L2 任务是 `harness task recover`），再让 agent 重新 `--dry-run`。
- **任务很大，要做很多天或跨多个 session**：输入 `/generic-goal-driven` 建目标，之后每个新 session 输入 `/generic-goal-driven 继续`。日常任务不要用。提示见 [07-prompts.md](07-prompts.md)。
- **看用量和拒绝次数**：`harness stats`。
- **要改 harness 自己，或查 harness 为什么出错**：在 agent 下拉里选 admin，照它给的命令在终端运行 `harness admin on`。用完运行 `harness admin off`。见 [02-features.md](02-features.md) 的“admin”一节。
