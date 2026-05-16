# PRD: Vault MCP Server v2.0 重构

**Author:** 刘利明
**Date:** 2026-05-15
**Status:** Draft
**Version:** 1.0
**Taskmaster Optimized:** Yes

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Problem Statement](#problem-statement)
3. [Goals & Success Metrics](#goals--success-metrics)
4. [User Stories](#user-stories)
5. [Functional Requirements](#functional-requirements)
6. [Non-Functional Requirements](#non-functional-requirements)
7. [Technical Considerations](#technical-considerations)
8. [Implementation Roadmap](#implementation-roadmap)
9. [Out of Scope](#out-of-scope)
10. [Open Questions & Risks](#open-questions--risks)
11. [Validation Checkpoints](#validation-checkpoints)
12. [Appendix: Task Breakdown Hints](#appendix-task-breakdown-hints)

---

## Executive Summary

Vault MCP Server v1.0 提供了知识库 CRUD + 代码图谱的基础能力（13 个 MCP 工具、SQLite + FTS5 全文搜索、graphify 代码图谱），已稳定支撑 4 个项目的知识管理。但在持续使用中暴露出**待办管理混乱**（每次 resume 看到已解决的待办）、**命令记忆负担重**（13 个子命令难以记忆）、**工具缺失**（无删除/追加）、**代码架构耦合**（单文件 600 行）四类问题。v2.0 重构将新建独立待办系统、重新设计会话日志/恢复流程、补全 CRUD 工具链、重构命令为独立 `/kb-<verb>` 体系，并将数据库层拆分为 6 个子模块、新增 services 业务层。目标是让知识库从"能用"提升到"好用"，降低日常操作摩擦。

---

## Problem Statement

### Current Situation

v1.0.3 已稳定运行，13 个 MCP 工具覆盖了基本的笔记 CRUD、图谱构建、日志记录。但在实际日常使用中，以下问题严重影响体验：

1. **待办混淆**：`vault_log` 中的 todos 是会话日志的历史快照，无法标记完成、无法跨会话追踪。每次 `/kb resume` 都会吐出所有历史日志的 todos，其中大部分早已解决，用户需要反复判断哪些真的需要处理。

2. **命令记忆负担**：`/kb` 下 13 个子命令（init/save/search/resume/list/stats/orphan/update/tags/log/graphify build/status/query）难以记忆，用户需要每次查阅文档。

3. **工具缺失**：没有 `vault_delete` 工具，删除笔记需要手动操作 SQLite。`vault_update` 只能替换正文，无法增量追加。

4. **架构耦合**：`vault_tools.py` 约 400 行、`db.py` 约 600 行，职责边界模糊（如 wikilink 检测在 tools 层而非 service 层）。错误处理模式不统一。

5. **测试覆盖不足**：工具层测试（~30 个）仅为路径覆盖，未覆盖边界情况和错误路径。

### User Impact

- **受影响用户**：所有使用 Vault MCP Server 的开发者（当前主要用户即作者本人）
- **痛点**：每次 resume 都遇到相同待办，产生"狼来了"效应，真正需要关注的待办被淹没
- **严重程度**：High — 核心日常流程（resume/log）的可用性问题

### Business Impact

- **效率损失**: 每次 `/kb resume` 后需要 2-3 分钟手动判断哪些待办真实有效，按每日 3 次 resume 计，每周浪费约 30 分钟。
- **数据风险**: 无 `vault_delete` 工具，手动操作 SQLite 容易误删或遗漏级联清理，已出现数据库残留记录问题（如 goldmind/e2e-test 项目）。
- **维护成本**: `db.py` 600 行单文件、`vault_tools.py` 400 行，新增功能时定位和修改成本递增。
- **用户增长**: 项目将作为个人知识管理基础设施长期使用，架构清晰化是持续演进的必要前提。

### Why Solve This Now?

v1.0.3 的代码量仍在可控范围（~1500 行），此时重构成本最低。随着项目继续使用，代码和技术债会持续增长，越晚重构代价越大。

---

## Goals & Success Metrics

### Goal 1: 消除待办混淆

- **Metric**: `/kb resume` 返回的待办均为"未完成"状态，0 条已完成的虚假待办
- **Baseline**: 当前 resume 返回所有历史日志的 todos，真假混合
- **Target**: resume 只返回 open 状态的 todos，已完成的不再显示

### Goal 2: 降低命令记忆负担

- **Metric**: 用户只需输入 `/kb` 即可看到所有可用命令和简短说明
- **Baseline**: `/kb` 无法独立使用，必须记住子命令或查看 SKILL.md
- **Target**: `/kb` 显示帮助面板，每个子命令有独立清晰的名字

### Goal 3: CRUD 操作完整性

- **Metric**: 笔记支持完整的增删改查 + 增量追加
- **Baseline**: 无删除工具，更新只能替换正文
- **Target**: 新增 `vault_delete` 工具，`vault_update` 支持追加模式

### Goal 4: 代码质量

- **Metric**: 测试覆盖率 >= 80%，文件最大行数 <= 400 行
- **Baseline**: 测试覆盖约 50-60%，vault_tools.py 约 400 行，db.py 约 600 行
- **Target**: 80%+ 覆盖率，按职责拆分 db.py，工具模块保持 200-300 行

---

## User Stories

### Story 1: 智能待办管理

**As a** 知识库使用者,
**I want to** 跨会话追踪待办状态，resume 时只看到真正未完成的事项,
**So that I can** 不被历史待办干扰，专注当前需要处理的事。

**Acceptance Criteria:**
- [ ] 新建独立的 `todos` 表（id, project, content, status, source_log_id, created, updated）
- [ ] `vault_log` 写入时，自动将 todos 同步到 `todos` 表（新建或更新）
- [ ] `vault_resume` 只展示 `status='pending'` 的待办
- [ ] 新增待办工具（命令即意图）：
  - `vault_todo_list(project)` — 列出项目待办
  - `vault_todo_done(id)` — 标记完成
  - `vault_todo_progress(id)` — 标记进行中
  - `vault_todo_pending(id)` — 恢复为待处理
  - `vault_todo_delete(id)` — 删除待办
- [ ] 在日志 `.md` 正文中，待办的 checklist 状态与实际状态保持一致

### Story 2: 清晰可发现命令体系

**As a** 知识库使用者,
**I want to** 只打 `/kb` 就能看到全部命令，每个命令有直观的 `/kb-<领域>-<动作>` 名字,
**So that I can** 不需要查文档就能使用。

**Acceptance Criteria:**
- [ ] `/kb` 显示帮助面板（列出全部 21 个命令 + 一句话描述）
- [ ] 全部命令扁平化，无二级嵌套：`/kb-save`, `/kb-search`, `/kb-log`, `/kb-resume`, `/kb-list`, `/kb-stats`, `/kb-tags`, `/kb-init`, `/kb-orphan`, `/kb-update`, `/kb-delete`, `/kb-learn`
- [ ] 待办命令：`/kb-todo-list`, `/kb-todo-done`, `/kb-todo-progress`, `/kb-todo-pending`, `/kb-todo-delete`
- [ ] 图谱命令：`/kb-graph-build`, `/kb-graph-status`, `/kb-graph-query`
- [ ] 更新 SKILL.md 映射表，所有命令路径可触发

### Story 3: 完整的笔记 CRUD

**As a** 知识库使用者,
**I want to** 能删除笔记、能增量追加内容,
**So that I can** 完整管理知识库而无需手动操作数据库。

**Acceptance Criteria:**
- [ ] `vault_delete(title)` 删除笔记：同时删除 .md 文件 + FTS 索引 + wikilink 引用 + 关联 todos
- [ ] `vault_update(title, append_content)` 支持 append 模式（追加到正文末尾）
- [ ] 删除前返回将被删除的笔记信息，供调用方确认

### Story 4: 架构清晰化

**As a** 项目维护者,
**I want to** 代码分层清晰、职责单一,
**So that I can** 理解和修改代码时定位更快。

**Acceptance Criteria:**
- [ ] `db.py` 拆分：`db/notes.py`（笔记 CRUD）、`db/todos.py`（待办）、`db/session.py`（日志）、`db/graph.py`（图谱构建）、`db/base.py`（连接/迁移）
- [ ] `tools/vault_tools.py` 对应拆分，每个工具模块聚焦单一领域
- [ ] 新增 `services/` 层：wikilink 检测、内容校验、标签统计、**标题定位（title → path 解析）**等业务逻辑从 tools 层抽离
- [ ] 统一错误处理装饰器，替换 ad-hoc try/except
- [ ] `vault_delete`、`vault_update` 支持标题直接定位，无需手动传 file_path
- [ ] `_shared.py` 新增 `get_project(args, vault_dir)` 函数：优先取传入 project → 否则从 `os.getcwd()` 目录名推断；推断后检查 `~/vault/<project>/` 是否已初始化，未初始化返回错误提示 `/kb-init`；所有需要 project 的工具统一调用此函数

### Story 5: 测试覆盖 80%+

**As a** 项目维护者,
**I want to** 有完整的测试套件,
**So that I can** 重构时不会意外破坏功能。

**Acceptance Criteria:**
- [ ] 数据库层测试覆盖所有新模块（notes/todos/session/graph）
- [ ] 工具层测试覆盖所有 CRUD 操作 + 错误路径
- [ ] 服务层测试覆盖 wikilink 检测、内容校验
- [ ] E2E 测试覆盖完整流程（init → save → search → update → todo → log → resume → delete）
- [ ] `pytest --cov` 报告中整体覆盖率 >= 80%

---

## Functional Requirements

### Must Have (P0)

#### REQ-001: 独立待办系统

**Description:** 新建 `todos` 表，支持跨会话状态追踪。`vault_log` 写入时同步 todos，`vault_resume` 只展示未完成待办。

**Technical Specification:**
```sql
CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT NOT NULL,
    content     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in-progress', 'done')),
    source_log_id INTEGER REFERENCES session_logs(id),
    created     TEXT DEFAULT (datetime('now')),
    updated     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_todos_project ON todos(project);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
```

**MCP 工具接口:**
```
vault_todo_list(project: str)         → 列出项目待办
vault_todo_done(id: int)              → 标记完成
vault_todo_progress(id: int)          → 标记进行中
vault_todo_pending(id: int)           → 恢复为待处理
vault_todo_delete(id: int)            → 删除待办
```

**vault_log 行为变更:** 写入 session_log 时，todos 同步到 `todos` 表。如果 content 相同的 pending todo 已存在，跳过（去重）。

**vault_resume 行为变更:** 从 `todos` 表读取 `status='pending'` 的待办，不再从 `session_logs.todos` JSON 字段读取。project 参数改为可选，未传时从 CWD 自动推断。

#### REQ-002: 命令重命名与帮助面板

**Description:** 将 `/kb <subcommand>` 模式改为独立 `/kb-<verb>` 命令，`/kb` 自身显示帮助。

**命令映射（21 个，全部扁平，/kb-<领域>-<动作>）:**
| 命令 | MCP 工具 | 参数 | project 来源 |
|------|---------|------|-------------|
| `/kb` | 帮助面板 | — | — |
| `/kb-init` | vault_init | — | — |
| `/kb-save` | vault_save | —（AI 推断） | CWD 自动 |
| `/kb-search` | vault_search | query | 可选过滤 |
| `/kb-resume` | vault_resume | — | CWD 自动 |
| `/kb-list` | vault_list | 筛选（可选） | CWD 自动 |
| `/kb-stats` | vault_stats | — | — |
| `/kb-tags` | vault_tags | query（可选） | — |
| `/kb-orphan` | vault_orphan | — | — |
| `/kb-update` | vault_update | title, append_content | CWD 自动 |
| `/kb-delete` | vault_delete | title | CWD 自动 |
| `/kb-learn` | vault_save | —（AI 推断全部） | —（强制 permanent/） |
| `/kb-log` | vault_log | summary | CWD 自动 |
| `/kb-todo-list` | vault_todo_list | — | CWD 自动 |
| `/kb-todo-done` | vault_todo_done | id | — |
| `/kb-todo-progress` | vault_todo_progress | id | — |
| `/kb-todo-pending` | vault_todo_pending | id | — |
| `/kb-todo-delete` | vault_todo_delete | id | — |
| `/kb-graph-build` | graphify_build | — | CWD 自动 |
| `/kb-graph-status` | graphify_status | — | CWD 自动 |
| `/kb-graph-query` | graphify_query | symbol | CWD 自动 |

**CWD 自动推断规则:** 所有需要 `project` 的 MCP 工具，如果用户未显式传入 project 参数，默认从当前工作目录（CWD）的目录名推断项目名。这是 v1.0.3 中 `vault_save` 已有模式，v2.0 扩展到全部工具。

**project 自动推断前检查初始化:** CWD 推断出 project 后，先检查 `~/vault/<project>/` 目录是否存在。如果不存在，说明项目尚未初始化，返回错误提示用户执行 `/kb-init`。用户显式传入 project 时也执行相同检查。

```
内部流程:
  1. get_project(args) → 取传入 project 或 CWD 推断
  2. 检查 ~/vault/<project>/ 是否存在
  3. 不存在 → 返回 {"status": "error", "message": "项目 xxx 尚未初始化，请先执行 /kb-init"}
  4. 存在 → 继续正常逻辑
```

**vault_search 项目优先级排序:** 搜索结果采用硬分组排序，确保当前工作项目的知识优先展示：

```
分组优先级（组内 BM25 排序）:
  第一组: 当前 project 匹配   ← 场景化知识，最高优先
  第二组: permanent/ 匹配     ← 通用知识，次优先
  第三组: 其他 project 匹配   ← 不相关项目，最低优先

当前在 B 项目，搜索 "浏览器 目录":
  1. "Chrome 安装" B项目/     (0.45)  ← 第一组
  2. "浏览器目录" permanent/  (0.92)  ← 第二组，虽得分高但非 B 项目
  3. "浏览器配置" A项目/      (0.38)  ← 第三组
```

**SKILL.md 更新:** 保持 `/kb` 作为总路由 skill，新增 `/kb-init` 等独立 skill 文件，每个文件极薄（仅做参数提取和 MCP 调用）。

**知识库优先原则（新增自动行为）:** Claude 在执行任何任务、做出任何假设之前，如果缺少关键上下文信息（路径、配置、技术栈、历史决策等），必须先调用 `vault_search` 搜索知识库，找到相关笔记后再继续。找不到才问用户或自行推断。

```
用户: "浏览器的目录在 D:\chrome"
  → /kb-learn 或 /kb-save → 存入 vault

日后用户在新会话中:
用户: "帮我修改浏览器的配置"
  → Claude 不知道浏览器在哪
  → 自动 vault_search("浏览器 目录") → 找到笔记
  → 知道 D:\chrome，继续执行
  → 用户无感知
```

这个原则适用于所有涉及用户环境信息的场景：项目路径、工具链配置、账号信息、历史决策、已知 bug 解决方案等。

### vault_save 参数详解

vault_save 是最核心的写入工具，5 个参数中 4 个必填（AI 自动推断）、1 个可选。

#### title — 笔记标题（必填）

字符串，非空，最长 200 字符。用中文简洁概括笔记内容。

```
title: "Windows Git Bash 中 subprocess stdin 导致超时"
```

**系统行为:**
- 自动生成文件名（kebab-case，中文移除仅保留英文 → `windows-git-bash-subprocess-stdin-dao-zhi-chao-shi.md`）
- 用作自动 wikilink 检测的基准标题（扫描正文时将其他已知标题替换为 `[[wikilink]]`）
- 标题对应的文件已存在时自动变为**更新模式**（覆盖正文 + 重建 FTS5 索引）

**标题精确匹配去重策略:** title 匹配限定在本作用域内（SQL `WHERE title = ? AND project = ?`，不走 FTS5，零额外 token 开销）。同一 project 内同标题直接更新；不同 project 的同标题笔记各自独立、互不覆盖。跨 project 的重复由标签重叠检测发现。

#### content — 笔记正文（必填）

Markdown 字符串，不含 frontmatter（系统自动生成）。建议结构：

```markdown
## 问题
...

## 原因
...

## 解决方案
...

## 相关
[[其他笔记标题]]  ← 手动 wikilink（系统也会自动检测并替换）
```

**系统行为:**
- 自动扫描正文中出现的已知笔记标题纯文本，替换为 `[[wikilink]]` 格式
- 统计字数（word_count），用于笔记质量评估
- 生成 SHA-256 checksum，用于内容变更检测

#### tags — 标签列表（必填）

字符串数组，每个标签最长 50 字符。使用中文或英文关键词：

```
tags: ["python", "subprocess", "mcp", "stdin", "devnull", "timeout"]
```

**系统行为:**
- 写入 `tag_index` 统计表（UPSERT 去重 + 使用频次）
- 标签通过 FTS5 索引可被全文搜索
- 作为去重第二层：同项目内 ≥3 个标签完全重叠时返回候选笔记 warning

#### type — 笔记类型（必填）

决定文件存储路由，共 6 种：

| type | 用途 | 有 project 时路径 | 无 project 时路径 | wikilink 要求 |
|------|------|------------------|------------------|-------------|
| `solution` | 问题解决方案 | `<project>/features/` | `permanent/` | — |
| `tool` | 工具使用技巧 | `<project>/data/` | `permanent/` | — |
| `concept` | 概念原理说明 | `<project>/architecture/` | `permanent/` | — |
| `permanent` | 永久知识笔记 | `<project>/architecture/` | `permanent/` | ≥ 2 个 |
| `session-log` | 会话日志（系统自动） | `<project>/logs/` | `logs/` | — |
| `code-graph` | 代码图谱（系统自动） | `graphify/<project>/` | `graphify/` | — |

```
type: "solution"        → vault/vault-mcp-server/features/xxx.md  (有 project)
type: "permanent"       → vault/permanent/xxx.md                   (无 project)
type: "code-graph"      → vault/graphify/<project>/xxx.md          (图谱专用)
type: "session-log"     → vault/<project>/logs/xxx.md              (日志专用)
```

**三个作用:**
1. **路由文件位置** — 不同 type 存到不同子目录，实现物理分类
2. **过滤和检索** — `vault_search` / `vault_list` 支持按 type 筛选；`vault_resume` 只查 `permanent` + `solution`；`vault_orphan` 排除 `session-log`
3. **内容校验** — `type: permanent` 需要至少 2 个 [[wikilink]]，不足返回 warning

**用户选择:**
```
日常问题解决  → solution     ← 最常用
工具技巧备忘  → tool
概念原理理解  → concept
需要多链 wiki → permanent   ← 深度知识
```

#### project — 归属项目（可选）

字符串。未传时自动从 CWD 目录名推断。显式传 `""` 或 `None` 强制进入 `permanent/` 目录。

```
CWD = D:\MyWord\vault-mcp-server
  → project 自动推断为 "vault-mcp-server"
  → 笔记存到 vault/vault-mcp-server/

CWD = C:\Users\Gzlance（用户主目录，推断无意义）
  → AI 显式传 project 参数
```

#### status — 已移除（v2.0）

v1.x 中 `status` 字段（draft/review/permanent）在个人知识库场景下无实际作用——存进去的知识默认可信，无需验证状态标记。v2.0 删除此字段，简化 save 流程。

#### 标签重叠辅助检测（去重第二层）

标题精确匹配未命中时，检查新笔记的 tags 与已有笔记的标签重叠度。同项目内 ≥3 个标签完全重叠视为潜在重复，返回 warning 列出候选笔记标题 + 路径 + 重叠数。

```
保存 "Chrome 安装路径" tags=["chrome", "browser", "directory"]

1. title 精确匹配 → 未命中
2. tags 重叠检测:
   → 找到 "浏览器目录" 也有 ["chrome", "browser", "directory"] → 3 个重叠
   → 返回 warning:
     {
       "warnings": [{
         "type": "possible_duplicate",
         "message": "可能存在重复笔记（标签重叠3个: chrome, browser, directory）",
         "candidates": [
           {"title": "浏览器目录", "file_path": "permanent/liu-lan-qi-mu-lu.md", "overlap_count": 3}
         ],
         "suggestion": "/kb-update 浏览器目录 更新旧笔记，或 /kb-delete 浏览器目录 删除旧的"
       }]
     }
   → AI 展示: "⚠️ 发现相似笔记 [浏览器目录]，更新还是删除旧的？"
```

1-2 个标签重叠太常见（如 `["python"]` 出现 50 次），不作为信号。标题不同的残留重复由 `/kb-orphan` 定期清理兜底。

### `/kb-learn` — 学习笔记（thin wrapper）

**功能:** 将学到的知识、概念、原理保存到知识库。底层直接调用 `vault_save`，但固定以下参数：

- **project**: 强制为空（`""`） → 绕过 CWD 检测，笔记存入 `permanent/` 目录
- **type**: AI 根据内容自动推断（`concept` 或 `permanent`）
- **title/tags/content**: AI 从对话中自动提取

**与 `/kb-save` 的区别:**

| | `/kb-save` | `/kb-learn` |
|---|---|---|
| 存储位置 | CWD 项目目录 | 强制 `permanent/` |
| 适用场景 | 项目相关的问题/方案/工具 | 跨项目的通用知识、概念、原理 |
| project | CWD 自动 | 强制为空 |

**示例（典型闭环）:**
```
第一步 — 用户传授知识:
  /kb-learn 浏览器的目录在 D:\chrome，配置文件在 D:\chrome\config.json
  → vault_save(title="浏览器目录与配置", content="...", type="tool", project="")

第二步 — 日后 Claude 自动查知识库:
  Claude 遇到需要浏览器目录的任务，不知道路径
  → 自动 vault_search("浏览器 目录") → 找到笔记 → 拿到 D:\chrome
  → 继续执行，用户无感知

第三步 — Claude 遇到报错也能自动搜:
  执行过程中碰到 "config not found"
  → 自动 vault_search("config") → 找到 D:\chrome\config.json
  → 自我修复
```

#### REQ-003: vault_delete 工具（标题定位 + 级联删除）

**Description:** 按**标题**定位并删除笔记，无需关心内部文件路径。级联清理关联数据。

**标题定位策略:**
1. 用标题在 `notes` 表中精确匹配 → 命中 1 条直接删除
2. 精确匹配多条 → 加 `project` 过滤（从 CWD 自动推断）
3. 仍有多条 → 返回候选列表，由 AI 让用户选择
4. 精确无命中 → FTS5 模糊搜索，得分最高且 > 阈值自动选，否则展示候选

**接口:**
```
vault_delete(title: str, project?: str) → {status: "ok", deleted: {title, file_path, wikilinks_removed, matched_by}}
```
- `matched_by`: "exact" | "project_filtered" | "fts5"

**级联删除:**
1. 删除 `.md` 文件
2. 删除 `notes` 表记录 → FTS5 自动同步
3. 删除 `wikilinks` 表中所有引用（source_path 或 target_path）
4. 删除关联 `todos`（通过 source_log_id 关联的日志待办保留，仅删除通过 note 关联的）
5. 更新 `tag_index` 标签计数

#### REQ-004: vault_update 标题定位 + 追加模式

**Description:** 按**标题**定位笔记，支持替换正文和/或追加内容。

**标题定位策略:** 与 `vault_delete` 相同（精确 → project 过滤 → FTS5 模糊 → 候选列表）。

**接口变更:**
```
vault_update(title: str, project?: str, new_content?: str, append_content?: str)
  → title 必填，定位笔记
  → new_content 和 append_content 至少传一个
  → 传 new_content: 替换正文（现有行为）
  → 传 append_content: 追加到正文末尾
  → 同时传: 先替换再追加
```

#### REQ-005: 数据库层拆分

**Description:** 将 600 行 `db.py` 按领域拆分为独立模块。

**目标结构:**
```
db/
├── __init__.py    # 导出 VaultDB 外观类
├── base.py        # 连接管理、迁移、WAL 配置 (~80 行)
├── notes.py       # 笔记 CRUD + FTS5 索引 (~150 行)
├── todos.py       # 待办 CRUD (~80 行)
├── session.py     # 会话日志 (~60 行)
├── graph.py       # 图谱构建记录 (~60 行)
└── wikilinks.py   # wikilink 引用图 (~80 行)
```

### Should Have (P1)

#### REQ-006: 服务层抽取

**Description:** 将 tools 层中的业务逻辑抽取到 `services/` 层。

```
services/
├── wikilink.py     # wikilink 检测 + 自动链接生成
├── validator.py    # frontmatter 校验、内容规则
├── tags.py         # 标签统计、去重、重叠检测（≥3 重叠 → 返回候选笔记 title+path+overlap_count，供用户决定更新/删除）
└── resolver.py     # 标题 → 路径解析（精确/exact+project/FTS5 三级匹配）
```

#### REQ-007: 统一错误处理

**Description:** 用装饰器统一 tools 层的错误处理模式。

```python
# 当前（每个 handler 重复）
try:
    db = VaultDB()
    ...
except Exception as e:
    return json_reply({"status": "error", "message": str(e)})

# 目标
@handle_errors
async def handle_save(args: dict) -> list[TextContent]:
    ...
```

#### REQ-008: 测试覆盖补充

**Description:** 补全测试覆盖到 80%+。

- `test_db_notes.py` — notes CRUD 全覆盖
- `test_db_todos.py` — todos 状态流转
- `test_db_session.py` — 日志读写
- `test_services.py` — wikilink 检测、校验
- `test_vault_delete.py` — 删除 + 级联
- `test_vault_todo.py` — 待办标记 + 列表
- 扩展 `e2e_test.py` — 覆盖新流程

### Nice to Have (P2)

#### REQ-009: vault_resume 增强

- 展示上次会话以来的 git commit 变化
- 展示 graphify 图谱新鲜度状态
- 按照"紧急度"排序待办（pending 优先，按照 created 升序）

---

## Non-Functional Requirements

### Performance

- 所有 MCP 工具响应时间 < 1s（本地 SQLite 操作，不涉及网络）
- `vault_resume` 额外查询 `todos` 表开销控制在 < 50ms
- 数据库 WAL 模式保持，允许并发读

### Compatibility

- Python 3.10+，保持标准库 `sqlite3` 依赖
- Windows 平台兼容（`PYTHONIOENCODING=utf-8`、Git Bash 路径）
- MCP stdio 协议不变
- **不向后兼容旧 session_logs 的 todos JSON 字段**（按用户决策）

### Code Quality

- `black` + `isort` + `ruff` 无告警
- `mypy` 类型检查通过
- 文件 <= 400 行，函数 <= 50 行
- 无 `print()` 残留，统一使用 `logging`

### Security

- SQL 参数化查询（已有，保持）
- 路径遍历防护：`vault_delete` 校验 note_path 在 vault_dir 内
- 输入校验：所有 MCP 工具入口处 check_required

---

## Technical Considerations

### Current Architecture

```
Claude Code ──MCP stdio──> server.py (269 行)
                               │
        ┌──────────────────────┼──────────────────────┐
        v                      v                      v
   vault_tools.py        graphify_tools.py        _shared.py
   (400+ 行，10工具)      (200 行，3 工具)          (47 行)
        │                      │
        └──────────┬───────────┘
                   v
              db.py (600 行, VaultDB 类)
                   │
                   v
            ~/vault/ (.md 文件)
```

### Proposed Architecture (v2.0)

```
Claude Code ──MCP stdio──> server.py (~300 行, 21 工具注册)
                               │
        ┌──────────────────────┼──────────────────────────┐
        v                      v                          v
   tools/                  tools/                      tools/
   ├── vault_init.py       graphify_build.py           _shared.py
   ├── vault_save.py       graphify_status.py
   ├── vault_search.py     graphify_query.py
   ├── vault_resume.py
   ├── vault_list.py
   ├── vault_stats.py
   ├── vault_orphan.py
   ├── vault_update.py
   ├── vault_tags.py
   ├── vault_log.py
   ├── vault_delete.py     ← 新增
   ├── vault_todo_list.py  ← 新增
   ├── vault_todo_done.py  ← 新增
   ├── vault_todo_progress.py ← 新增
   ├── vault_todo_pending.py ← 新增
   └── vault_todo_delete.py ← 新增
        │                      │
        └──────────┬───────────┘
                   v
            services/              ← 新增层
            ├── wikilink.py
            ├── validator.py
            ├── tags.py
            └── resolver.py
                   │
                   v
            db/                    ← 拆分
            ├── base.py
            ├── notes.py
            ├── todos.py
            ├── session.py
            ├── graph.py
            └── wikilinks.py
                   │
                   v
            ~/vault/ (.md 文件)
```

### Key Design Decisions

1. **tools 文件拆分策略**: 每个 MCP 工具独立一个 `tools/vault_xxx.py` 文件，server.py 负责导入和路由。这样可以独立测试每个工具。

2. **VaultDB 外观类**: `db/__init__.py` 提供 `VaultDB` 类，内部委托给各子模块。对外接口不变（`with VaultDB() as db: ...`），内部调用转发到对应子模块。

3. **服务层边界**: `services/` 是纯函数层，不依赖数据库连接。输入数据 → 变换 → 输出结果。tools 层调用 services 做业务处理，再通过 db 层持久化。

4. **待办与日志的关系**: todos 通过 `source_log_id` 关联到创建它的 session_log。vault_log 写入时 upsert todos（相同 content + project 的 pending todo 去重）。

5. **命令路由**: 21 个命令全部扁平化（`/kb-<领域>-<动作>`），无二级嵌套。SKILL.md 保持 `/kb` 作为帮助入口，新增独立 skill 文件。每个 skill 文件极薄（< 20 行），只做 MCP 工具调用。待办命令采用"命令即意图"设计（`/kb-todo-done 3` 比 `/kb-todo mark 3 done` 更简洁）。

6. **知识重复检测分层策略（三级，均零 token）:**
   - 第一层：标题精确匹配（SQL `WHERE title = ? AND project = ?`，project 作用域隔离）→ 命中直接更新，覆盖 90%
   - 第二层：标签重叠检测（SQL `json_each` 交集）→ 同 project 内 ≥3 个标签重叠，返回 warning 列出候选（含 title + path + overlap_count）
   - 第三层：`/kb-orphan` 定期清理 → 人工发现标题不同的遗留重复
   - 三层都不走 FTS5，不在每次 save 时增加 token 开销

7. **搜索项目优先级（硬分组，不加权）:**
   - 搜索排序：当前 project > permanent/ > 其他 project
   - 组内 BM25 排序，组间不混合。确保当前项目知识绝对优先

8. **CWD 自动推断项目**: 所有需要 `project` 的 MCP 工具，统一调用 `_shared.get_project(args)` 工具函数。逻辑：优先取用户传入的 `project`，否则从 `os.getcwd()` 目录名推断。v1.0.3 中 `vault_save` 已有此模式，v2.0 扩展到 resume/list/todo/graph/build/status/query/delete/update/log。

### Database Migration

v2.0 需要执行以下 DDL 变更（幂等，使用 IF NOT EXISTS）：

```sql
-- 新增 todos 表
CREATE TABLE IF NOT EXISTS todos (...);

-- session_logs 表不变（保留旧数据作为历史，但不再从 todos JSON 字段读取）
```

旧 `session_logs.todos` JSON 字段保留但不再被 `vault_resume` 使用。按用户决策，不执行数据迁移。

### Testing Strategy

- 使用 `pytest` + `unittest.mock.patch` 隔离文件系统和外部依赖
- 数据库测试使用共享连接（`_SharedVaultDB`）避免 Windows 文件锁
- E2E 测试使用临时目录（`tmp_path` fixture）
- 目标覆盖率 80%+，CI 中通过 `--cov-fail-under=80` 强制执行

---

## Implementation Roadmap

重构分为 5 个阶段，建议按依赖顺序执行：

### Phase 1: 数据库层重构 (P0)
**目标:** 拆分 db.py，建立新表结构，保持对外接口兼容。

- 创建 `db/` 包，拆分为 base/notes/todos/session/graph/wikilinks
- 实现 `VaultDB` 外观类，委托到子模块
- 新增 `todos` 表 DDL
- 现有 82 个测试全部通过

### Phase 2: 服务层 + 新工具 (P0)
**目标:** 实现 todos 系统、vault_delete、vault_update 追加。

- 创建 `services/` 层（wikilink/validator/tags）
- 实现 `vault_todo_list`、`vault_todo_done`、`vault_todo_progress`、`vault_todo_pending`、`vault_todo_delete`
- 实现 `vault_delete`（含级联清理）
- `vault_update` 追加模式
- `vault_log` 同步 todos 到 `todos` 表
- `vault_resume` 改为从 `todos` 表读取

### Phase 3: 工具模块拆分 (P1)
**目标:** 将 vault_tools.py 拆分为独立文件，server.py 更新路由。

- 每个工具独立一个 `tools/vault_xxx.py`
- server.py 更新 tool schema 注册和分发
- 统一错误处理装饰器

### Phase 4: 命令重命名 (P1)
**目标:** 实现 `/kb-<verb>` 命令体系。

- 创建独立 SKILL.md 文件（`/kb-save`, `/kb-log` 等）
- `/kb` 更新为帮助面板
- 更新 CLAUDE.md 文档

### Phase 5: 测试补全 (P1)
**目标:** 测试覆盖率达到 80%+。

- 为所有新增/修改模块编写测试
- 扩展现有 E2E 测试
- CI 中配置 `--cov-fail-under=80`

---

## Out of Scope

1. **Obsidian 插件集成** — 不在本次重构范围
2. **多用户支持** — Vault 是个人知识库，无多用户需求
3. **图数据库迁移** — 保持 SQLite，不引入 Neo4j 等
4. **Web UI** — 保持 MCP stdio 协议，不添加 HTTP 接口
5. **增量图谱更新** — graphify 保持全量构建模式

---

## Open Questions & Risks

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| 数据库重构导致回归 | Medium | High | Phase 1 后运行全部 82 个现有测试 |
| 工具拆分引入导入循环 | Low | Medium | 依赖方向：tools → services → db，单向 |
| Windows 文件锁问题 | Medium | Medium | 保持 `_SharedVaultDB` 模式 |
| 重构期间中断使用 | High | Low | 在开发目录重构，运行目录保持 v1.0.3 |

---

## Validation Checkpoints

### Checkpoint 1: Phase 1 完成
- [ ] `db/` 包导入正常，82 个测试通过
- [ ] `VaultDB` 外观类接口不变
- [ ] `todos` 表创建成功

### Checkpoint 2: Phase 2 完成
- [ ] vault_todo_list / vault_todo_done / vault_todo_progress / vault_todo_pending / vault_todo_delete 工作正常
- [ ] vault_delete 级联清理正确
- [ ] vault_log → todos 同步正确
- [ ] vault_resume 只显示 pending 待办

### Checkpoint 3: Phase 3 完成
- [ ] 所有工具独立文件，server.py 正确路由
- [ ] 错误处理装饰器覆盖全部 handler
- [ ] 现有测试通过（更新导入路径后）

### Checkpoint 4: Phase 4 完成
- [ ] `/kb` 显示帮助面板
- [ ] 各 `/kb-<verb>` 命令可独立触发（21 个扁平命令）

### Checkpoint 5: Phase 5 完成
- [ ] `pytest --cov` >= 80%
- [ ] E2E 测试覆盖完整新流程

---

## Appendix: Task Breakdown Hints

### Suggested Task Structure (约 25 个任务)

**Phase 1: 数据库层重构 (6 tasks)**
1. 创建 `db/` 包结构，拆出 `base.py`（连接管理 + 迁移） — **无依赖**
2. 拆出 `db/notes.py`（笔记 CRUD + FTS5） — **依赖: #1**
3. 拆出 `db/session.py`（会话日志） — **依赖: #1**
4. 拆出 `db/graph.py`（图谱构建记录） — **依赖: #1**
5. 拆出 `db/wikilinks.py`（引用图） — **依赖: #1**
6. 实现 `db/__init__.py` VaultDB 外观类 + 新增 `todos` 表 — **依赖: #2, #3, #4, #5**

**Phase 2: 服务层 + 新工具 (6 tasks)**
7. 创建 `services/wikilink.py`（从 tools 层抽离） — **依赖: #6**
8. 创建 `services/validator.py`（frontmatter 校验） — **依赖: #6**
9. 创建 `services/tags.py`（标签统计 + 重叠检测：≥3 重叠返回候选笔记的 title + file_path + overlap_count，附带建议命令） — **依赖: #6**
9a. 创建 `services/resolver.py`（标题 → 路径解析：精确 → project 过滤 → FTS5 模糊 三级匹配） — **依赖: #6**
10. 实现 `tools/vault_todo_list.py` + `tools/vault_todo_done.py` + `tools/vault_todo_progress.py` + `tools/vault_todo_pending.py` + `tools/vault_todo_delete.py` — **依赖: #6**
11. 实现 `tools/vault_delete.py`（按标题定位，三级匹配 + 级联删除） — **依赖: #6, #9a**
12. 修改 `vault_update` 为标题定位 + 追加模式（title → path 解析 + replace/append）+ `vault_log` 同步 todos + `vault_resume` 用新逻辑 — **依赖: #9a, #10**

**Phase 3: 工具模块拆分 (4 tasks)**
13. 拆分 `tools/vault_tools.py` 为独立文件（init/save/search/list/stats/orphan/update/tags/log/resume） — **依赖: #12**
14. 更新 `server.py` 工具注册和分发路由 — **依赖: #13**
15. 更新 `tools/_shared.py`：新增 `get_project(args, vault_dir)`（CWD 推断 + 检查项目是否已初始化，未初始化返回 `/kb-init` 提示）+ 统一错误处理装饰器 `@handle_errors` — **依赖: #13**
16. 验证全部 13 个现有工具正常工作 — **依赖: #14, #15**

**Phase 4: 命令重命名 (3 tasks)**
17. 创建独立 SKILL.md 文件（全部 21 个扁平命令：kb-save/kb-log/kb-resume/kb-search/kb-learn/kb-list/kb-stats/kb-tags/kb-init/kb-orphan/kb-update/kb-delete/kb-todo-list/kb-todo-done/kb-todo-progress/kb-todo-pending/kb-todo-delete/kb-graph-build/kb-graph-status/kb-graph-query） — **依赖: #16**
18. 更新 `/kb` SKILL.md 为帮助面板 — **依赖: #17**
19. 更新 CLAUDE.md 文档 — **依赖: #17, #18**

**Phase 5: 测试补全 (6 tasks)**
20. 补全 `db/` 层测试（notes/todos/session） — **依赖: #6**
21. 补全 `services/` 层测试 — **依赖: #7, #8, #9, #9a**
22. 补全 `tools/` 层新增工具测试（todo/delete/resolver） — **依赖: #9a, #10, #11**
23. 扩展现有工具测试覆盖 — **依赖: #14**
24. 扩展 E2E 测试 — **依赖: #22, #23**
25. 配置 CI 覆盖率门禁 — **依赖: #24**

**总计: ~25 个任务**

### Critical Path
1 → 6 → 9a → 11 → 12 → 17 → 20

---

**End of PRD**
