# 配置与定制

harness 本身不含任何业务内容。接入公司环境时，你加四样东西：目标仓库、知识库、策略覆盖、技能。

## override：只写要改的项

每个策略 `.harness/policies/<名>.json` 都可以有同名的 `<名>.override.json`。只有一层，写在旁边，不改默认文件。

合并规则：

- 对象：逐项合并。
- 其他值（包括数组）：整体替换。
- `"<键>+": [...]`：往默认数组里追加。

例子：往 gate 的 guardrail 里追加一个路径，并把 git 批准的有效时间改短。

```json
{
  "guardrail_paths+": ["config/prod/**"],
  "git": { "approval_minutes": 5 }
}
```

- `doctor` 会列出每个 override 改了哪些项，写错会报错。
- 核心 guardrail 删不掉：override 里去掉它们，gate 也会加回来，`doctor` 报错。
- `*.override.json` 属于使用者。含本机路径的（例如 `target.override.json`）不要提交，仓库的 `.gitignore` 已忽略它。

## 目标仓库

新建 `.harness/policies/target.override.json`：

```json
{
  "repos_root": "/Users/你/repos",
  "repos": {
    "bdtt_repo": { "refused_paths": [".git/**", ".github/workflows/**"] },
    "other_repo": { "path": "/elsewhere/other_repo", "base_ref": "develop" }
  }
}
```

| 字段 | 含义 |
| --- | --- |
| `repos_root` | 一个文件夹。它下面每个带 `.git` 的子文件夹是一个目标仓库，名字是文件夹名 |
| `repos` | 名字到设置：`path` 指向别处的仓库；`base_ref` 改这个仓库的取文件分支；`refused_paths` 改这个仓库不许回写的路径 |
| `base_ref` | 取文件的分支，默认 `main`。要在本地存在 |
| `refused_paths` | promote 不写、agent 也不能直接写的路径（git 风格 glob）。`.git/**` 总是被保护 |

- 路径里的 `~`、`%USERPROFILE%`、`$HOME` 会展开。
- 仓库名只能用字母、数字、`_`、`.`、`-`。
- 检查：`doctor`（列出每个仓库、分支、有没有未提交的文件）和 `target list`。

## 知识库

`knowledge-base/` 是接入公司知识库的位置，仓库里保持为空。接入后：

1. 把知识库放进 `knowledge-base/`。**入口是 `knowledge-base/README.md`**：它是索引，只放主题和相对链接，agent 先读它，再按需往下读，不要一次读全部。
2. 把讲知识库怎么读、怎么写的 instructions 放进 `.github/instructions/`（例如 `knowledgebase.instructions.md`），frontmatter 写 `applyTo: '**'`。只写 `applyTo: 'knowledge-base/**'` 不够：agent 读到知识库文件之前它不会生效。
3. 运行 `doctor`。它检查：有没有 README、README 里的链接是否都有文件、`.gitignore` 有没有忽略 `knowledge-base/`、instructions 会不会被加载。
4. 知识库的写作规则只有一个主要来源：知识库自带的 instructions。orchestrator 读知识库后，把结论蒸馏成带来源的“知识简报”（`brief set`），之后每个角色共用。

## 技能（Skills）

技能放在 `.github/skills/<名>/SKILL.md`，规则见 [skills.instructions.md](../.github/instructions/skills.instructions.md)。

- 目录名和 `name` 必须一致，用前缀：`harness-<模块>`（harness 自带）、`generic-<名>`（通用）、`domain-<领域>-<名>`（你们的业务技能）。
- `description` 写清“什么时候用”，它是 agent 决定要不要读全文的唯一依据。
- 业务技能用 `domain-` 前缀，和自带的分开，方便以后升级 harness 时不冲突。
- 新建技能可以用 `generic-build-new-skill`。

## agent 与模型

自定义 agent 在 `.github/agents/`：`orchestrator`（L3 入口）、`builder`、`reviewer`、`verifier`。

- 每个 agent 文件的 `model` 列表按顺序回退。[agents.json](../.harness/policies/agents.json) 规定：回退只能在同一个系列内；builder 和 reviewer 必须不同系列（`doctor` 检查）。
- 改模型名时，改 agent 文件的 `model`，再运行 `doctor`。

## 日志和清理

- 日志在 `.harness/runtime/`，不进 git。`logs prune --days <N>` 删掉 N 天没写过的会话日志，先用 `--dry-run` 看。
- 想知道某个运行环境的 hook 实际收到什么：在 `observe.override.json` 里把 `capture.enabled` 设为 `true`，原始输入输出会存到 `.harness/runtime/capture/`。用完关掉。

## 路径太长（Windows）

请求目录加仓库路径会让文件路径很长，Windows 默认上限 260 个字符。把 harness 放在短路径、不同步的位置（例如 `C:\h`），不要放在 OneDrive 下。`doctor` 会对过长的路径给 WARN。
