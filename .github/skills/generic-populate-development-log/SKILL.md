---
name: generic-populate-development-log
description: '将当前 session 已完成的 harness 升级写入 .local/开发日志.md。用于一次 session 完成一次开发后，按日期、核心组件更新和前后对比 Outcome 新增或修正一条开发日志。'
type: unit
specificTo: harness-development
---

# 写入 Harness 开发日志

把当前 session 已完成的 harness 改动整理成一条短日志，并写入 `.local/开发日志.md`。

## 使用时机

- 当前 session 已完成一次 harness 升级，需要记录开发结果。
- 用户要求补写或修正当前 session 的开发日志。

## 工作流

1. 只从当前 session 的对话上下文提取事实。收集已完成的改动、验证结果和直接效果。
2. 读取 `.local/开发日志.md`。只用它确认格式、插入位置和当前 session 是否已经写过，不把旧日志当成本次改动的事实来源。
3. 如果当前 session 没有已经完成的改动，停止写入并说明原因。
4. 使用运行环境的本地日期和时间。日期格式为 `YYYY-MM-DD`，时间格式为 `HH:mm`。
5. 写一个能说明本次升级内容的短标题。
6. 将改动归入下列分类，只保留本次实际改动过的分类：
   - `instructions`
   - `agents`
   - `skills`
   - `tools`
   - `hooks`
   - `knowledge-base`
   - `harness 其他功能（具体方向）`
7. 将 contracts、eval、observability、permission control、optimization 和未列出的 harness 能力归入 `harness 其他功能`，并写明具体方向。
8. 为每个分类写简短 bullet point。说明改了什么，以及它现在如何工作。不要写过程流水账。
9. 写 1～3 条 Outcome。每条都用具体的前后对比，格式为“以前……；现在……”。
10. 在 `DEVELOPMENT_LOG_ENTRIES_START` 和 `DEVELOPMENT_LOG_ENTRIES_END` 之间写入条目：
    - 已有当天日期时，在该日期标题下方插入本次记录。
    - 没有当天日期时，在开始标记下方新增日期和记录。
    - 日期和同一天的记录都保持从新到旧。
11. 如果本 session 已经写过一条日志，修改那一条。不要再新增一条。
12. 写入后重读新增或修改的条目。确认分类准确、Outcome 简短，并且没有重复条目。

条目使用以下结构：

```markdown
### YYYY-MM-DD

#### HH:mm｜本次升级标题

##### 一、核心组件更新

- **skills**
  - 改了什么，以及它现在如何工作。

##### 二、Outcome

- 以前……；现在……。
```

## Gotchas

- **不要读取 Git 历史、Git diff、提交记录或其他仓库文件来补全本次内容。** 本 Skill 的事实来源只能是当前 session。
- **不要记录计划或声称没有验证过的效果。** 只写当前 session 已经完成并确认的内容。
- **不要列出未改动的分类。** 空分类会让真正的改动难以看到。
- **不要写空话。** “提升了效率”“增强了能力”必须改成可观察的前后差异。
- **不要改动其他文件。** 本 Skill 只写 `.local/开发日志.md`。
- **不要删除或改写其他 session 的记录。** 修正范围只限当前 session 创建的条目。

## 故障处理

| 问题 | 处理方式 |
| --- | --- |
| 找不到 `.local/开发日志.md` | 停止写入，并请用户确认本地资料目录或恢复日志模板。 |
| 找不到日志边界标记 | 不猜插入位置。停止写入，并请用户确认是否恢复模板标记。 |
| 无法确认某项改动是否完成 | 不记录该项；需要它出现在日志中时，向用户确认。 |
