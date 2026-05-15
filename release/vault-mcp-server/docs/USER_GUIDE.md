# Vault MCP Server 使用手册

**版本:** 2.0 | **更新:** 2026-05-15 | **目标用户:** Claude Code 用户

---

## 1. 快速开始

### 1.1 前置条件

- Python 3.10+
- Claude Code（已配置 MCP）
- pip 已安装依赖（`mcp>=1.0.0`）

### 1.2 安装

```bash
# Linux/macOS
bash release/install.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File release/install.ps1
```

### 1.3 初始化知识库

```
/kb-init
```

首次使用执行一次即可。幂等操作，重复执行不会损坏数据。

---

## 2. 命令参考（21 个扁平命令）

所有命令采用 `/kb-<领域>-<动作>` 格式。输入 `/kb` 即可查看全部命令。

### 2.1 笔记 CRUD

| 命令 | 参数 | 说明 |
|------|------|------|
| `/kb-save` | — (AI 推断) | 保存笔记，CWD 自动 project |
| `/kb-search <关键词>` | query 必填 | FTS5 全文搜索 |
| `/kb-list` | 筛选条件可选 | 列出笔记 |
| `/kb-update <标题>` | title + 内容 | 更新/追加笔记内容 |
| `/kb-delete <标题>` | title 必填 | 标题定位 + 级联删除 |
| `/kb-learn` | — (AI 推断) | 保存学习笔记到 permanent/ |

**搜索优先级:** 当前项目 > permanent/ > 其他项目（硬分组，组内 BM25）。

**去重策略:** title 精确匹配自动更新（零 token）；标签重叠 ≥3 时提示候选笔记。

### 2.2 会话与恢复

| 命令 | 说明 |
|------|------|
| `/kb-resume` | 恢复上下文：最近日志 + 架构笔记 + 未完成待办（CWD 自动 project） |
| `/kb-log <摘要>` | 写会话日志，todos 自动同步到待办表 |

### 2.3 待办管理

| 命令 | 说明 |
|------|------|
| `/kb-todo-list` | 列出待办（CWD 自动 project） |
| `/kb-todo-done <id>` | 标记完成 |
| `/kb-todo-progress <id>` | 标记进行中 |
| `/kb-todo-pending <id>` | 恢复待处理 |
| `/kb-todo-delete <id>` | 删除待办 |

`/kb-log` 中的 todos 会自动写入独立待办表，跨会话追踪。

### 2.4 代码图谱

| 命令 | 说明 |
|------|------|
| `/kb-graph-build [项目]` | 构建代码图谱 |
| `/kb-graph-status [项目]` | 查看图谱状态 |
| `/kb-graph-query <符号>` | 搜索符号调用链 |

### 2.5 管理

| 命令 | 说明 |
|------|------|
| `/kb-init` | 初始化 Vault 目录 + 数据库 |
| `/kb-stats` | 统计面板 |
| `/kb-tags` | 标签列表及频次 |
| `/kb-orphan` | 孤立笔记检测 |

---

## 3. 使用流程示例

### 3.1 新项目起步

```
/kb-init              ← 初始化（仅首次）
/kb-graph-build .     ← 构建代码图谱
/kb-resume            ← 每次会话恢复上下文
```

### 3.2 解决 Bug 后保存

```
/kb-save              ← AI 自动提取问题、方案、标签
/kb-log 修复了 XX bug  ← 写日志（todos 同步）
```

### 3.3 管理待办

```
/kb-resume            ← 查看未完成待办
/kb-todo-done 3       ← 标记 #3 已完成
/kb-todo-progress 5   ← 标记 #5 进行中
```

### 3.4 清理过期知识

```
/kb-orphan            ← 发现孤立笔记
/kb-delete 过时的笔记   ← 标题定位删除
```

---

## 4. 笔记类型

`/kb-save` 的 `type` 参数决定存储位置（AI 自动推断，用户无需手动指定）：

| type | 用途 | 有 project | 无 project |
|------|------|-----------|-----------|
| `solution` | 问题解决方案 | `<project>/features/` | `permanent/` |
| `tool` | 工具使用技巧 | `<project>/data/` | `permanent/` |
| `concept` | 概念原理 | `<project>/architecture/` | `permanent/` |
| `permanent` | 永久知识 | `<project>/architecture/` | `permanent/` |
| `session-log` | 会话日志（自动） | `<project>/logs/` | `logs/` |
| `code-graph` | 代码图谱（自动） | `graphify/<project>/` | `graphify/` |

---

## 5. MCP 工具参考（21 个）

| MCP 工具 | 功能 |
|----------|------|
| `vault_init` | 初始化 Vault 目录 + 数据库 |
| `vault_save` | 保存笔记（title/content/tags/type 必填，project/status 已移除） |
| `vault_search` | FTS5 全文搜索（硬分组排序） |
| `vault_resume` | 恢复上下文（project 可选，从 todos 表读待办） |
| `vault_list` | 列出笔记 |
| `vault_stats` | 统计面板 |
| `vault_orphan` | 孤立笔记检测 |
| `vault_update` | 更新/追加笔记 |
| `vault_tags` | 标签列表 |
| `vault_log` | 写会话日志（同步 todos） |
| `vault_delete` | 标题定位删除（三级解析 + 级联） |
| `vault_todo_list` | 列出待办 |
| `vault_todo_done` | 标记完成 |
| `vault_todo_progress` | 标记进行中 |
| `vault_todo_pending` | 恢复待处理 |
| `vault_todo_delete` | 删除待办 |
| `graphify_build` | 构建代码图谱 |
| `graphify_status` | 图谱状态 |
| `graphify_query` | 搜索符号 |

---

## 6. 常见问题

### Q: project 参数需要手动传吗？

不需要。所有需要 project 的工具自动从 CWD 推断。如果项目未初始化，会提示执行 `/kb-init`。

### Q: 如何删除笔记？

`/kb-delete <标题>`。支持三级标题定位（精确 → project 过滤 → FTS5 模糊），级联清理 .md + 索引 + wikilink + 标签统计。

### Q: 待办和日志中的 todos 是什么关系？

`/kb-log` 写入日志时，todos 自动同步到独立的 `todos` 表。`/kb-resume` 从 `todos` 表读取未完成待办。`/kb-todo-*` 命令管理待办状态。

### Q: status 字段去哪了？

v2.0 移除了笔记的 `status` 字段（draft/review/permanent）。存入的知识默认可信，不需要状态标记。
