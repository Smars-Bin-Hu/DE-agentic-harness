# 短命令怎么配

目标：在任何终端里输入 `harness` 都能运行。做法只有一种：让启动脚本在 PATH 里。

启动脚本在仓库的 `.harness/bin/`：`harness`（macOS/Linux）、`harness.cmd`（Windows）。

下面的命令**给用户，请用户在自己的终端运行**。把 `<仓库>` 换成这个仓库的完整路径（你用 `pwd` 查到的，Windows 用 `(Get-Location).Path`），不要让用户自己填。

## 先判断

| 看什么 | 怎么看 |
| --- | --- |
| 系统 | 提示开头的环境信息；或运行 `uname`（macOS/Linux 有输出，Windows 的 PowerShell 没有这个命令） |
| shell（macOS/Linux） | `echo $SHELL`。结尾是 `zsh` 改 `~/.zshrc`，是 `bash` 改 `~/.bashrc` |
| 是不是已经有自己的 PATH 文件夹 | `echo $PATH` 里有 `~/bin` 或 `~/.local/bin` 时，直接把链接建在那里，不用再改 PATH |

## macOS / Linux

```bash
mkdir -p ~/bin
ln -sf "<仓库>/.harness/bin/harness" ~/bin/harness
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
```

- `~/bin` 已经在 PATH 里时，不要第三行。
- bash 把 `~/.zshrc` 换成 `~/.bashrc`。
- 建的是链接，不是复制：仓库升级后不用重配。

## Windows

把 `<仓库>\.harness\bin` 加进**用户**的 PATH。两种做法给用户选：

- 界面：系统设置里搜“环境变量”→“编辑账户的环境变量”→ 选 `Path` → 编辑 → 新建 → 填 `<仓库>\.harness\bin`。
- PowerShell（只改用户变量，不用管理员权限）：

```powershell
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";<仓库>\.harness\bin", "User")
```

公司电脑不让改环境变量时，告诉用户：这一步是必须的，要找 IT 加这一条用户 PATH。

## 做完之后

1. **重开终端，也重开 VS Code。** 不重开 VS Code，agent 的终端认不到新的 PATH。
2. 运行 `harness --version --short`，应输出 `harness <版本>`。
3. 运行 `harness doctor`，开头几行里应有一行 `[OK]`，写着“短命令 `harness` 在 PATH 里”。

## 电脑上有两份 harness

`harness` 像 git：从当前目录往上找 `.harness/engine/cli.py`，找到哪一份就操作哪一份。不在任何 harness 仓库里时，才用 PATH 里那个启动脚本自己所在的那一份。

所以 PATH 里只要有一份的启动脚本就够，两份仓库都能用。`doctor` 这时会给一条 WARN，说 PATH 里的不是这个仓库的，可以不管。

例外：PATH 里那一份是 1.0.2 之前的版本时，它不会找当前目录，永远操作它自己那一份。这时把 PATH 改成指向新的这一份。
