---
name: harness-repo-initialize
description: '拿到 harness 仓库后的第一次配置：配好短命令 harness、接入知识库和公司技能、配置目标仓库和用户名字，最后用 doctor 检查。用户输入 /harness-repo-initialize，或说“初始化 harness”“第一次配置”“harness 命令找不到”“doctor 报短命令的错”时用。关键词：初始化、initialize、setup、安装、第一次用、PATH、短命令、target.override.json、接入知识库。'
type: workflow
specificTo: generic
---

# 初始化 harness 仓库

带用户把一份刚拿到的 harness 仓库配到能用：短命令、知识库、公司技能、目标仓库、用户名字。每一项做完都用 `doctor` 检查。

## When to Use This Skill

- 用户刚克隆或解压了 harness 仓库，第一次用。
- `harness` 命令找不到，或 `doctor` 报“PATH 里找不到短命令”。
- 用户换了电脑、换了仓库的位置，要重新配。
- 用户要补配其中一项（例如只接入知识库）：只做那一步，再做最后的检查。

日常任务不用它。要改 hook、engine、默认策略，用 admin agent，不用本技能。

## Prerequisites

- Python 3.9 或更新，git。
- 用户能打开自己的终端。短命令和 admin 模式都要用户亲手运行命令。
- 写 `.harness/policies/*.override.json` 要 admin 模式（第 2 步开）。短命令那一步不用。

## Step-by-Step Workflows

开始时把下面的清单发给用户，做完一项勾一项。用户说某项以后再配，就标“跳过”，接着做下一项。

```markdown
- [ ] 1. 短命令 harness（必须）
- [ ] 2. 开 admin 模式
- [ ] 3. 用户名字
- [ ] 4. 目标仓库
- [ ] 5. 知识库和它的 instructions
- [ ] 6. 公司技能
- [ ] 7. 其他覆盖配置（可选）
- [ ] 8. 检查
```

1. **短命令（必须，先做）。** 运行 `harness --version --short`。
   - 输出 `harness <版本>`：已经配好，跳到第 2 步。
   - 找不到命令：先自己运行只读的 `uname`、`echo $SHELL`、`echo $PATH`（Windows 不用），按 [短命令怎么配](./references/short-command.md) 的“先判断”选出要给的命令。PATH 里已有 `~/bin` 就不给改 shell 配置文件的那一条。把命令给用户，请用户**在自己的终端**运行，然后**重开终端和 VS Code**。你不运行这些命令。用户说做完了，再运行一次 `harness --version --short` 确认。
   - 这一步没通过，不做后面的。后面的命令都以 `harness` 开头。
2. **开 admin 模式。** 看提示开头的规则。没写“admin 模式：已开”时，把 `harness admin on --session-id <当前会话 id>` 给用户，请用户在自己的终端运行并输入确认码。会话 id 原样抄规则里的。你不能自己运行它。
3. **用户名字。** 运行 `harness user`。
   - `source` 是 `user.override.json`：已配好。
   - 其他情况：把查到的名字给用户看，问要不要用它，或换一个。用户给了名字，按 [user.override.json](./templates/user.override.json) 写 `.harness/policies/user.override.json`。用户说就用 git 的名字，不写文件。
4. **目标仓库。** 问用户：代码仓库都放在哪个文件夹；有没有不在那个文件夹里的仓库；取文件的分支是不是都叫 `main`；哪些路径不许 agent 碰（部署配置、流水线定义）。按 [target.override.json](./templates/target.override.json) 写 `.harness/policies/target.override.json`，只留用到的字段。然后运行 `harness target list`，把仓库名和分支给用户核对。字段的意思见 [docs/03-configure.md](../../../docs/03-configure.md) 的“目标仓库”。
5. **知识库。** 问用户知识库现在在哪（一个文件夹的路径）。
   - 把它的内容放进 `knowledge-base/`。入口必须是 `knowledge-base/README.md`。
   - 把知识库自带的、讲怎么读怎么写的 instructions 放进 `.github/instructions/knowledgebase.instructions.md`，frontmatter 写 `applyTo: '**'`。
   - 用户还没有知识库：标“跳过”，并告诉用户影响（见 Gotchas）。
6. **公司技能。** 问用户有没有公司专用的技能，在哪。每个技能一个文件夹，放进 `.github/skills/`。文件夹名和 `SKILL.md` 的 `name` 要一致，用 `domain-<领域>-<名>` 前缀。前缀不对时告诉用户，问清楚再改名，不要自己改。
7. **其他覆盖配置（可选）。** 问用户有没有要改的默认值。常见的两个：CLI 的中文显示成 `\uXXXX`（见 Troubleshooting）；要多保护几个路径（`gate.override.json` 的 `extra_guardrail_paths+`）。规则见 [docs/03-configure.md](../../../docs/03-configure.md) 的“override”。没有就跳过。
8. **检查。** 运行 `harness doctor`。
   - `[ERROR]`：照信息修，修完再运行，直到 `{"errors": 0}`。修不了的，原样告诉用户。
   - `[WARN]`：逐条告诉用户它影响什么，由用户决定修不修。
   - 最后给用户一张表：八项各是“配好、跳过、没通过”，跳过的各有什么影响。提醒用户运行 `harness admin off --session-id <会话 id>`，并换一个新对话做日常任务。

## Gotchas

- **改 PATH 的命令只给用户，不自己运行。** 它改的是仓库之外的文件（`~/.zshrc`、Windows 的用户环境变量）。harness 的规则是 agent 不改用户的环境。
- **配完 PATH 必须重开 VS Code。** Copilot 的终端用的是 VS Code 启动时的 PATH。只重开终端窗口，你自己运行 `harness` 仍然找不到。
- **不要教用户用 alias 或 PowerShell 函数。** 它们只在用户自己的交互式终端里有效，agent 的终端里没有，`doctor` 也查不到。
- **`harness` 操作的是当前目录所在的那一份仓库。** 电脑上有两份 harness 时，在哪一份里运行就操作哪一份。所以命令要在这个仓库里运行。
- **只写 `*.override.json`，不改默认的策略文件。** 默认文件以后升级会被覆盖。`target.override.json`、`user.override.json` 含本机的路径和名字，已被 git 忽略，不要提交。
- **不要往 `knowledge-base/` 里编内容。** 用户没有知识库就空着。没有知识库时，agent 做目标仓库的任务只能靠猜，计划和检查都不准：这一点要明确告诉用户。
- **知识库的 instructions 的 `applyTo` 要是 `'**'`。** 只写 `'knowledge-base/**'` 时，agent 读到知识库文件之前它不生效。
- **复制大的知识库用终端命令**（`cp -R`，Windows 用 `Copy-Item -Recurse`），不要一个文件一个文件地读了再写。
- **不要自己决定跳过哪一项。** 每一项都问用户；用户说跳过才跳过。

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 用户说配了 PATH，`harness` 还是找不到 | 先确认重开了 VS Code。再让用户在自己的终端运行 `echo $PATH`（Windows：`echo $env:Path`），看有没有那个文件夹。macOS 上最常见的原因：只建了链接，没把 `~/bin` 加进 PATH |
| `doctor` 说 PATH 里的 `harness` 不是这个仓库的 | 电脑上有另一份 harness。能用，但建议让 PATH 指向常用的那一份。见 [短命令怎么配](./references/short-command.md) |
| 写 `*.override.json` 被拒绝 | admin 模式没开，或开的是别的会话。回到第 2 步 |
| `harness target list` 没列出仓库 | `repos_root` 下的子文件夹要有 `.git`。路径写错时 `doctor` 会报 |
| `doctor` 报知识库的 README 里有断链 | 链接要用相对路径，指向 `knowledge-base/` 里真实存在的文件。把断的几条告诉用户 |
| CLI 输出的中文是 `\uXXXX` | 看 `doctor` 最后的 `[INFO]  UTF-8 样例` 一行。能读，就写 `.harness/policies/cli.override.json`：`{"output": {"encoding": "utf-8"}}`。是乱码就不要改，告诉用户 |
| Windows 上 `python3` 找不到 | 正常。Windows 用 `python`，启动脚本会自己选 |
