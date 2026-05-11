# PRD: Claude Code 记忆系统 + 知识库

**作者:** Gzlance
**日期:** 2026-05-09
**更新:** 2026-05-11
**状态:** Review
**版本:** 2.1

---

## 目录

1. [摘要](#摘要)
2. [问题陈述](#问题陈述)
3. [目标与成功指标](#目标与成功指标)
4. [用户故事](#用户故事)
5. [命令清单](#命令清单)
6. [功能需求](#功能需求)
7. [非功能需求](#非功能需求)
8. [技术方案](#技术方案)
9. [数据模型](#数据模型)
10. [MCP 工具规格](#mcp-工具规格)
11. [实施路线图](#实施路线图)
12. [范围外](#范围外)
13. [待解决问题与风险](#待解决问题与风险)
14. [验收检查点](#验收检查点)

---

## 摘要

Claude Code 内置记忆系统（`.claude/projects/`）按项目隔离，无法跨项目共享知识。本方案基于 **Obsidian Vault** 构建统一个人知识库，通过 **MCP Server** 提供结构化存储、全文索引和代码图谱能力，辅以一份轻量 Skill 做路由指令。工作或生活中解决的问题、学到的知识，一句话就能按 Vault 模板持久化，后续在任何项目中都能检索复用。

---

## 问题陈述

### 当前现状

- Claude Code 内置记忆按项目隔离，项目 A 解决的问题在项目 B 中无法自动引用
- 知识以对话形式存在，对话结束后随上下文窗口消失
- 没有结构化的知识沉淀机制——知道「我之前解决过这个问题」，但找不到当时的方案
- 生活中学到的知识（技术文章、工具技巧、踩坑记录）散落在各处
- 代码结构理解每次都要重新读源码，新接手的项目尤其耗时

### 用户画像

| 维度 | 描述 |
|------|------|
| 目标用户 | 全栈开发者，日常工作涉及多个项目 |
| 技术背景 | Python、TypeScript、C#、Claude Code 深度用户 |
| 使用场景 | 跨项目知识复用、踩坑记录、技术笔记沉淀、会话上下文恢复、代码结构快速理解 |
| 痛点 | 知识碎片化，解决过的问题下次还要重新查；新项目代码结构理解成本高 |

### 为什么现在做

- Obsidian Vault 方案已在社区验证（[wangjun.dev](https://www.wangjun.dev/2026/05/claude-code-memory-setup/)、[lucasrosati/claude-code-memory-setup](https://github.com/lucasrosati/claude-code-memory-setup)）
- Vault 本质就是 Markdown 文件夹，不绑定特定工具
- MCP 协议成熟，Python SDK 已稳定，SQLite 零配置
- graphify (tree-sitter AST) 提供代码结构自动提取，与 Vault 天然互补
- 知识积累有复利效应：越早建，越早受益

---

## 目标与成功指标

### 目标 1: 知识沉淀零摩擦

- **指标:** 从「决定保存」到「笔记写入完成」的交互次数
- **目标:** 一句话触发，最多 1 次确认，无需手动编辑 Markdown
- **测量方式:** 实际使用计时

### 目标 2: 跨项目知识检索

- **指标:** 在任意项目中检索到相关知识笔记的成功率
- **目标:** FTS5 BM25 排序，返回 Top 10 匹配笔记，命中率 ≥ 80%
- **测量方式:** 抽样 10 个已知知识点验证

### 目标 3: 上下文恢复速度

- **指标:** 从键入命令到总结完上次工作状态的时间
- **目标:** < 5 秒
- **测量方式:** 实际计时

### 目标 4: 代码结构可视化

- **指标:** 新项目首次构建图谱的时间 + 图谱笔记可用性
- **目标:** 中等规模项目（~200 源文件）< 30 秒构建；图谱笔记在 Obsidian Graph View 中可交互浏览
- **测量方式:** 实际构建计时 + Obsidian 验证

---

## 用户故事

### 故事 1: 解决完问题，一句话保存

**As a** 开发者,
**I want to** 解决一个技术问题后，对 Claude Code 说「总结成知识笔记保存」,
**So that I can** 将来遇到同类问题时快速找到方案。

**验收标准:**
- [ ] 用户输入 `/kb save` 或自然语言「把这个保存到知识库」
- [ ] MCP `vault_save` 校验 YAML frontmatter 完整性
- [ ] SQLite 标题索引自动匹配已有笔记，生成 wikilink 候选列表返回
- [ ] 写入 `~/vault/permanent/`，文件名 kebab-case
- [ ] 写入后更新 SQLite 全文索引和标签索引
- [ ] 返回笔记路径，确认保存成功

**估时:** ~5h (MCP 工具 3h + 路由指令 2h)

---

### 故事 2: 跨项目搜索知识

**As a** 开发者,
**I want to** 在新项目中遇到问题时，用 `/kb search <关键词>` 搜索以前积累的知识,
**So that I can** 复用之前的解决方案，不重复踩坑。

**验收标准:**
- [ ] 用户输入 `/kb search <关键词>`
- [ ] MCP `vault_search` 用 FTS5 + BM25 全文索引搜索
- [ ] 返回 JSON：标题、片段高亮、标签、创建日期、相关度分数
- [ ] 支持 `--tag` 标签过滤、`--project` 项目过滤、`--type` 类型过滤
- [ ] 搜索结果自动覆盖 `graphify/` 目录下的代码图谱笔记

**估时:** ~3h (MCP 工具)

---

### 故事 3: 恢复工作上下文

**As a** 开发者,
**I want to** 每天开始工作或切换项目时，用 `/kb resume` 恢复上次的状态,
**So that I can** 快速进入工作状态，不需要翻聊天记录。

**验收标准:**
- [ ] 用户输入 `/kb resume`
- [ ] MCP `vault_resume` 定位项目 logs/ 和 architecture/，返回最近文件内容
- [ ] Claude 总结：上次做了什么、待办事项、关键决策
- [ ] 如果无历史记录，提示「该项目暂无知识库记录」

**估时:** ~3h (MCP 工具 2h + 路由指令 1h)

---

### 故事 4: 学习新知识，随手记录

**As a** 终身学习者,
**I want to** 阅读技术文章或学到新东西时，对 Claude Code 说「记录这个知识点」,
**So that I can** 把碎片化学习成果归集到统一的知识库。

**验收标准:**
- [ ] 用户输入 `/kb learn <内容或URL>`
- [ ] Claude 提取核心概念，用自己话重写
- [ ] MCP `vault_save` 生成原子化笔记（一个概念一篇）
- [ ] 自动 wikilink 到已有相关笔记
- [ ] 默认 `status: draft`

**估时:** ~4h (MCP 工具 2h + 路由指令 2h)

---

### 故事 5: 浏览与管理知识库

**As a** 知识库维护者,
**I want to** 查看知识库整体状态、发现孤立笔记、整理过时内容,
**So that I can** 维护知识网络健康。

**验收标准:**
- [ ] `/kb list` — MCP `vault_list` 按条件结构化列表查询，支持分页
- [ ] `/kb stats` — MCP `vault_stats` SQL 聚合统计（总数、分布、趋势）
- [ ] `/kb orphan` — MCP `vault_orphan` wikilink 引用图分析，找出入度为 0 的笔记
- [ ] `/kb update <笔记名>` — MCP `vault_update` 写入更新并刷新索引

**估时:** ~4h (MCP 工具)

---

### 故事 6: 代码图谱自动生成

**As a** 开发者,
**I want to** 对项目运行 `/kb graphify build`，自动生成代码结构笔记到 Vault,
**So that I can** 在 Obsidian 中可视化代码模块关系，快速理解项目架构。

**验收标准:**
- [ ] 用户输入 `/kb graphify build`
- [ ] MCP `graphify_build` 调用 `graphify update . --force`（AST 模式，无需 API Key）
- [ ] 解析 `graphify-out/graph.json` 生成模块笔记到 `~/vault/graphify/<project>/`
- [ ] 生成索引笔记 `Index.md`
- [ ] 构建完成后 `/kb search` 可检索图谱笔记
- [ ] `/kb graphify status` 返回上次构建时间、节点数、社区数
- [ ] `/kb graphify query <符号名>` 搜索代码符号及其所属模块

**估时:** ~6h (MCP 工具)

---

## 命令清单

### 核心命令 (P0)

| 命令 | 功能 | MCP 工具 | 频率 |
|------|------|----------|------|
| `/kb init` | 初始化 Vault 目录 + 模板 + SQLite | `vault_init` | 一次性 |
| `/kb save` | 保存知识笔记 | `vault_save` + `vault_tags` | 高频 |
| `/kb search <关键词>` | FTS5 全文检索 | `vault_search` | 高频 |
| `/kb resume` | 恢复项目上下文 | `vault_resume` | 中频 |
| `/kb learn <内容>` | 学习记录 | `vault_save` + `vault_tags` | 中频 |

### 管理命令 (P1)

| 命令 | 功能 | MCP 工具 |
|------|------|----------|
| `/kb list` | 条件列表查询 | `vault_list` |
| `/kb stats` | 知识库统计面板 | `vault_stats` |
| `/kb orphan` | 孤立笔记检测 | `vault_orphan` |
| `/kb update <笔记名>` | 更新已有笔记 | `vault_update` |

### 代码图谱命令 (P1)

| 命令 | 功能 | MCP 工具 |
|------|------|----------|
| `/kb graphify build` | 构建代码图谱 → Vault | `graphify_build` |
| `/kb graphify status` | 图谱构建状态 | `graphify_status` |
| `/kb graphify query <符号>` | 查询代码符号归属 | `graphify_query` |

---

## 功能需求

### 必须实现 (P0) — MVP

#### REQ-001: `vault_init` — 初始化

- 创建 Vault 目录树：`permanent/`、`templates/`、`logs/`、`graphify/`、`<project>/` 子目录
- 写入笔记模板文件 `default-note.md`、`session-log.md`（含 YAML frontmatter 骨架）
- 自动生成 `~/vault/CLAUDE.md`（Vault 使用规则，含笔记规范和三层代码查询策略）
- 初始化 SQLite 数据库（6 表 + FTS5 trigram 索引 + 12 辅助索引）
- 所有 DDL 使用 `IF NOT EXISTS`，**幂等操作**——已初始化的部分自动跳过
- 指定 `project` 参数时额外创建项目子目录（`architecture/`、`features/`、`data/`、`logs/`）

#### REQ-002: `vault_save` — 知识保存

- 输入参数：`title`（≤200 字符）、`content`（Markdown 正文）、`tags`（每个 ≤50 字符）、`type`、`project`、`status`
- 输入校验遵循 fail fast 原则：`check_required` → `check_title` → `check_tags` 逐层校验
- **自动 wikilink 原地替换**：检测正文中出现的已存笔记标题纯文本，自动替换为 `[[title]]` 格式（不含已处于 `[[]]` 内的文本），返回 `wikilinks_auto_suggested` 计数
- `type: permanent` 时校验 wikilink 数量 ≥ 2，不足则返回 `warnings` 提示补充链接
- 生成 kebab-case 文件名（中文→拼音映射，特殊字符移除），按类型/项目路由到目标目录
- **磁盘空间检查**：写入前检查目标分区剩余空间 < 10MB 则拒绝写入
- **文件名冲突检测**：同名文件存在但属于不同笔记时，追加数字后缀（如 `title-2.md`）
- 写入 .md 文件后同步更新 SQLite：notes 表、notes_fts 全文索引（内容 SHA256 checksum）、tag_index 标签计数、wikilinks 引用图
- 支持新建和更新两种模式，返回 `action: "created" | "updated"`

#### REQ-003: `vault_search` — 全文检索

- FTS5 全文索引 + BM25 相关度排序
- 支持参数：`query`（关键词）、`--tag`、`--project`、`--type`、`--limit`
- 返回 JSON：`{title, snippet (匹配片段高亮), tags, created, path, score}`
- 搜索范围覆盖 `permanent/` + `<project>/` + `graphify/`

#### REQ-004: `vault_resume` — 上下文恢复

- 输入参数：`project`（项目名）
- 定位 `~/vault/<project>/logs/` 中最近 N 个会话日志（按 mtime 排序）
- 定位 `~/vault/<project>/architecture/` 中的架构决策笔记
- 返回文件内容（可按行数截断），供 Claude 阅读理解

### 应该实现 (P1)

#### REQ-005: `vault_list` — 结构化列表

- 支持参数：`--tag`、`--project`、`--type`、`--status`、`--sort`、`--limit`、`--offset`
- 返回笔记列表，每条含标题、标签、日期、wikilink 数量

#### REQ-006: `vault_stats` — 统计面板

- 笔记总数、按 type 分布、按 project 分布
- Top 10 标签、最近 7 天新增数、总 wikilink 数、平均链接密度

#### REQ-007: `vault_orphan` — 孤立笔记检测

- 解析所有笔记的 wikilink `[[...]]` 和 frontmatter，构建引用图
- 找出入度为 0 的笔记（没被任何笔记引用）
- 找出出度为 0 的笔记（不引用任何其他笔记）

#### REQ-008: `vault_update` — 更新笔记

- 输入：`note_path` 或 `note_title`、`new_content` 或 `append_content`
- 保留原有 frontmatter，更新 `updated` 日期，重新索引

#### REQ-009: `vault_tags` — 标签索引

- 返回所有已用标签及使用频次
- 支持标签模糊搜索
- 笔记入库时自动更新标签计数

#### REQ-010: `vault_log` — 会话日志

- 输入：`project`、`summary`（必填）、`decisions`（字符串列表）、`todos`（字符串列表）
- 生成文件名：`YYYY-MM-DD-session-HHMMSS.md`（精确到秒，防止同一日内冲突）
- decisions 和 todos 以 JSON 数组格式存入 SQLite `session_logs` 表
- 按项目模板生成 Markdown 文件，写入 `<project>/logs/` 或全局 `logs/`

### 代码图谱 (P1)

#### REQ-011: `graphify_build` — 构建代码图谱

- 依赖 `graphify` CLI（`pip install graphifyy`），用 AST 模式无需 API Key
- 执行 `graphify update . --force`，解析 `graph.json`
- 生成模块笔记到 `~/vault/graphify/<project>/`，含索引 `Index.md`
- 自动生成 `.graphifyignore` 排除 obj/bin/node_modules
- 笔记写入后更新 SQLite 索引

#### REQ-012: `graphify_status` — 图谱状态

- 返回：上次构建时间、节点数、边数、社区数、图谱笔记数
- 检测图谱是否比最新 commit 旧

#### REQ-013: `graphify_query` — 代码符号查询

- 在 graph.json 中精确/模糊匹配符号名
- 返回：文件路径、所属社区（模块）、调用/被调用关系

### 锦上添花 (P2)

#### REQ-014: 标签自动建议

- 基于笔记内容关键词规则自动推荐标签

#### REQ-015: Git 自动同步

- Vault 纳入 Git 版本控制，`/kb save` 可选自动 commit

#### REQ-016: Git Hooks 集成

- post-commit 自动触发图谱重建和会话日志写入

---

## 非功能需求

### 性能

| 指标 | 目标 |
|------|------|
| `vault_save` 执行时间（含索引更新） | < 1 秒 |
| `vault_search` FTS5 检索（1000 篇笔记） | < 50ms |
| `vault_resume` 执行时间 | < 100ms |
| `vault_init` 执行时间 | < 2 秒 |
| `graphify_build`（200 源文件项目） | < 30 秒 |
| MCP Server 启动时间 | < 1 秒 |
| MCP Server 常驻内存 | < 50MB |

### 数据格式

- 所有笔记为 Markdown 文件（`.md`），UTF-8 编码
- YAML frontmatter 必填：`title`、`tags`、`created`、`updated`、`status`、`type`
- 文件名 kebab-case
- 内部链接使用 Obsidian wikilink 格式 `[[note-name]]`，禁止 markdown 链接
- 每篇 `type: permanent` 的笔记至少包含 2 个 wikilink
- SQLite 数据库存储索引和元数据，不存储笔记正文（正文始终是 .md 文件）

### 兼容性

- **操作系统:** Windows 11（本机）+ macOS/Linux
- **终端:** Git Bash（Windows）
- **Python:** 3.10+，标准库优先
- **可选依赖:** Obsidian 客户端（可视化浏览）、graphify CLI（代码图谱）

### 可靠性

- `vault_save` 写入前检查磁盘空间
- 文件名冲突自动追加数字后缀
- 不修改用户已有笔记（只追加、不覆盖）
- `PYTHONIOENCODING=utf-8` 避免 Windows GBK 乱码
- MCP Server 崩溃不影响 Vault 文件完整性

### 可扩展性

- 笔记模板在 `~/vault/templates/` 下可自定义
- MCP 工具独立可测试，新工具可直接追加
- Vault 目录结构可按项目类型扩展

---

## 技术方案

### 架构总览

```text
Claude Code ──MCP stdio──> server.py (注册+分发)
                               │
        ┌──────────────────────┼──────────────────────┐
        v                      v                      v
   vault_tools.py        graphify_tools.py        _shared.py
   (知识库 CRUD)         (代码图谱)                (校验/响应)
        │                      │
        └──────────┬───────────┘
                   v
              db.py (SQLite + FTS5)
                   │
                   v
            ~/vault/ (.md 笔记文件)
```

**分层职责：**

| 层级 | 文件 | 职责 |
|------|------|------|
| **入口层** | `server.py` | MCP stdio 通信、13 个 Tool schema 注册、`call_tool()` 分发路由 |
| **工具层** | `tools/vault_tools.py` | 10 个知识库工具处理函数（`async def handle_xxx`） |
| | `tools/graphify_tools.py` | 3 个代码图谱工具处理函数 |
| | `tools/_shared.py` | 公共层：`check_required`/`check_title`/`check_tags` 输入校验 + `json_reply` 响应封装 |
| **数据层** | `db.py` | `VaultDB` 类：6 表 DDL + FTS5 全文索引 + 12 辅助索引，上下文管理器管理事务，WAL 模式 |
| **存储层** | `~/vault/` | Obsidian Vault 目录，Markdown 文件持久化，SQLite 仅存索引和元数据 |

### 代码查询三层策略

Claude 修改代码前按优先级逐层查，上层信息足够时不再深入：

```
用户: "这个 Bug 在哪" / "怎么改这个功能"
         │
         ▼
┌─────────────────────────────────────────────┐
│ 第一层: graph.json / GRAPH_REPORT.md         │
│ • graphify_query(symbol) → 符号归属+调用链   │
│ • graphify_status() → 模块概览               │
│ 耗时: <10ms    消耗: ~100 token              │
└────────────────────┬────────────────────────┘
                     │ 信息不够
                     ▼
┌─────────────────────────────────────────────┐
│ 第二层: Vault 图谱笔记 + 知识笔记             │
│ • vault_search() → graphify/ + permanent/    │
│ • vault_resume() → 项目架构决策               │
│ 耗时: <50ms    消耗: ~500 token              │
└────────────────────┬────────────────────────┘
                     │ 仍不够（需看具体代码）
                     ▼
┌─────────────────────────────────────────────┐
│ 第三层: 直接读源文件                          │
│ • 前两层定位到具体文件后，精确 Read            │
│ 耗时: 视文件    消耗: 视文件                  │
└─────────────────────────────────────────────┘
```

**写入 CLAUDE.md 的规则:**

```markdown
## 代码查询策略
修改代码前，按优先级逐层查询：
1. 第一层: graphify_query + GRAPH_REPORT.md（符号归属和调用链）
2. 第二层: vault_search 搜 graphify/ 和 permanent/（模块职责和历史方案）
3. 第三层: 仅当前两层不足时，才 Read 原始代码文件

## 知识库规则
解决问题后提示用户是否保存，确认后调用 vault_save。
```

### 实现层级

| 层级 | 职责 | 技术 |
|------|------|------|
| **路由层** | `/kb` 命令 → MCP 工具映射 | Claude Code Skill（~20 行 .md 指令文件） |
| **MCP 层** | 结构化存储、全文索引、代码图谱、引用图分析 | Python MCP Server + SQLite |
| **存储层** | Markdown 笔记持久化 + 索引/元数据 | 文件系统 `~/vault/` + SQLite |
| **图谱层** | 代码 AST 提取 → 图谱笔记 | graphify CLI (tree-sitter) |
| **可视化层** | 知识图谱浏览（可选） | Obsidian 客户端 |

### 输入校验层

所有工具在处理请求前经过统一的三层校验（`tools/_shared.py`），遵循 **fail fast** 原则：

| 校验函数 | 职责 | 规则 |
|----------|------|------|
| `check_required(args, *fields)` | 必填参数检查 | 字段缺失或为空字符串时返回 `{"status": "error", "message": "缺少必填参数: xxx"}` |
| `check_title(title)` | 标题校验 | 非空、非纯空白、≤ 200 字符 |
| `check_tags(tags)` | 标签校验 | 必须为 list 类型，每个标签 ≤ 50 字符 |

所有响应通过 `json_reply(data)` 统一封装为 `list[TextContent]`，确保 `ensure_ascii=False`（中文不转义）。

### 路由 Skill 规格

极薄，只做命令分发：

```markdown
# /kb 知识库路由

## init
用户说「初始化知识库」「/kb init」→ 调用 MCP `vault_init`

## save
用户说「保存到知识库」「/kb save」→
1. 回顾对话，提取问题背景、解决方案、关键代码
2. 确定 title、tags、type
3. 调用 `vault_save`
4. 告知用户保存结果

## search
用户说「搜索知识库」「/kb search <关键词>」→ 调用 `vault_search`

## resume / learn / list / stats / orphan / update / graphify
依此类推，每个命令指向对应 MCP 工具
```

### 项目结构

```
~/.claude/
├── skills/
│   └── kb.md                       # /kb 路由指令（薄 Skill）
└── mcp.json                        # MCP Server 注册配置

~/vault/                            # Obsidian Vault
├── CLAUDE.md                       # Vault 使用规则（含三层查询策略）
├── permanent/                      # 永久知识笔记
├── templates/
│   ├── default-note.md
│   └── session-log.md
├── logs/                           # 全局会话日志
├── <project>/                      # 项目笔记
│   ├── architecture/
│   ├── features/
│   ├── data/
│   └── logs/
└── graphify/                       # 代码图谱笔记
    └── <project>/
        ├── Index.md
        └── Community-*.md

vault-mcp-server/                   # MCP Server 源码
├── server.py                       # MCP 入口：13 个工具注册 + 分发
├── tools/
│   ├── _shared.py                  # 公共层：输入校验 + JSON 响应封装
│   ├── vault_tools.py              # 10 个知识库工具处理函数
│   └── graphify_tools.py           # 3 个图谱工具处理函数
├── db.py                           # SQLite 数据层（VaultDB 类）
├── tests/
│   ├── test_db.py                  # 数据库层单元测试（~82 个）
│   ├── test_vault_tools.py         # 工具层集成测试（~30 个）
│   ├── test_graphify_tools.py      # 图谱工具测试（~25 个）
│   └── e2e_test.py                 # 端到端流程测试（14 步）
├── docs/
│   └── prd-knowledge-base.md       # 本文档
├── requirements.txt                # mcp>=1.0.0, graphifyy (可选)
├── CLAUDE.md                       # 项目开发规范
└── README.md
```

---

## 测试策略

### 测试架构

```
tests/
├── test_db.py              # VaultDB 单元测试（~82 个）
├── test_vault_tools.py     # 工具处理函数集成测试（~30 个）
├── test_graphify_tools.py  # 图谱工具集成测试（~25 个）
└── e2e_test.py             # 端到端流程测试（14 步完整工作流）
```

### 测试框架

- **pytest** 作为主测试运行器
- **unittest** 用于 E2E 测试（`unittest.TestCase` 基类）
- **unittest.mock.patch** 隔离外部依赖（文件系统、graphify CLI）

### Windows 兼容专项

SQLite 在 Windows 上存在文件锁竞争问题。E2E 测试使用 `_SharedVaultDB` 模式：

```python
class _SharedVaultDB(VaultDB):
    """所有 handler 共享同一个 SQLite 连接，避免 Windows 文件锁定。"""
    _instance = None

    @classmethod
    def create_shared(cls, db_path):
        cls._instance = object.__new__(cls)
        cls._instance.db_path = Path(db_path)
        cls._instance._connect()
        cls._instance.initialize()
        return cls._instance
```

- 测试中不创建新的 `VaultDB` 实例，而是复用 `_SharedVaultDB` 单例
- 通过 `patch("tools.vault_tools.VaultDB", lambda: cls._shared_db)` 注入
- 测试结束时不关闭连接，由 `_real_close()` 统一清理

### 覆盖率目标

| 指标 | 目标 | 当前状态 |
|------|------|----------|
| 总体行覆盖率 | ≥ 80% | ✅ 达标 |
| DB 层覆盖 | ≥ 85% | ✅ 82 个测试覆盖全部 CRUD + FTS + 统计 |
| 工具层覆盖 | ≥ 80% | ✅ 覆盖正常路径 + 错误路径 + 边界条件 |
| E2E 流程 | 14 步全覆盖 | ✅ init → save×3 → search → list → stats → tags → update → log → resume → orphan → graphify → 幂等验证 |

---

## 数据模型

### SQLite 表结构

```sql
-- 笔记索引表（不存正文，正文在 .md 文件）
CREATE TABLE notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    file_path   TEXT NOT NULL UNIQUE,     -- 相对于 ~/vault/ 的路径
    tags        TEXT,                      -- JSON 数组: ["csharp", "dotnet"]
    type        TEXT NOT NULL DEFAULT 'permanent',
    project     TEXT,                      -- 归属项目名
    status      TEXT DEFAULT 'draft',
    created     TEXT NOT NULL,            -- YYYY-MM-DD
    updated     TEXT NOT NULL,
    word_count  INTEGER DEFAULT 0,
    checksum    TEXT                       -- .md 文件 SHA256, 用于检测外部修改
);

-- FTS5 全文索引（trigram 分词，中英文混合内容均有效）
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title,
    content,                               -- .md 文件正文
    tokenize='trigram'
);

-- 标签使用统计
CREATE TABLE tag_index (
    tag         TEXT PRIMARY KEY,
    count       INTEGER DEFAULT 0,
    last_used   TEXT
);

-- wikilink 引用图（有向边）
CREATE TABLE wikilinks (
    source_path TEXT NOT NULL,             -- 引用方笔记路径
    target_path TEXT NOT NULL,             -- 被引用方笔记路径
    context     TEXT,                       -- 链接周围的上下文文本
    PRIMARY KEY (source_path, target_path)
);

-- 辅助索引（12 个）
CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type);
CREATE INDEX IF NOT EXISTS idx_notes_project ON notes(project);
CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated);
CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title);
CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created);
CREATE INDEX IF NOT EXISTS idx_wikilinks_source ON wikilinks(source_path);
CREATE INDEX IF NOT EXISTS idx_wikilinks_target ON wikilinks(target_path);
CREATE INDEX IF NOT EXISTS idx_session_logs_project ON session_logs(project);
CREATE INDEX IF NOT EXISTS idx_session_logs_date ON session_logs(date);
CREATE INDEX IF NOT EXISTS idx_graphify_builds_project_built_at
    ON graphify_builds(project, built_at);

-- graphify 构建记录
CREATE TABLE graphify_builds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT NOT NULL,
    commit_sha  TEXT,
    node_count  INTEGER,
    edge_count  INTEGER,
    community_count INTEGER,
    built_at    TEXT DEFAULT (datetime('now'))
);

-- 会话日志
CREATE TABLE session_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT,
    date        TEXT NOT NULL,            -- YYYY-MM-DD
    file_path   TEXT NOT NULL UNIQUE,     -- 文件名含时分秒: YYYY-MM-DD-session-HHMMSS.md
    summary     TEXT,
    decisions   TEXT,                      -- JSON 数组: ["决策1", "决策2"]
    todos       TEXT                       -- JSON 数组: ["待办1", "待办2"]
);
```

### 笔记 frontmatter 规格

```yaml
---
title: "Windows Git Bash 中 disown 的替代方案"
tags: [windows, git-bash, shell, process-management]
created: 2026-05-09
updated: 2026-05-10
status: permanent
type: solution
project: claudetest
---
```

---

## MCP 工具规格

### 核心工具 (P0)

#### `vault_init`

```json
{
  "name": "vault_init",
  "description": "初始化 Vault 目录结构、模板文件和 SQLite 索引库。幂等操作。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "vault_dir": { "type": "string", "default": "~/vault" },
      "project": { "type": "string", "description": "可选，同时初始化项目子目录" }
    }
  }
}
```

#### `vault_save`

```json
{
  "name": "vault_save",
  "description": "保存知识笔记到 Vault。校验 frontmatter、匹配 wikilink、更新索引。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "title": { "type": "string" },
      "content": { "type": "string", "description": "Markdown 正文（不含 frontmatter）" },
      "tags": { "type": "array", "items": { "type": "string" } },
      "type": { "enum": ["permanent", "solution", "concept", "tool", "session-log", "code-graph"] },
      "project": { "type": "string" },
      "status": { "enum": ["draft", "permanent", "review", "archived"], "default": "draft" }
    },
    "required": ["title", "content", "tags", "type"]
  }
}
```

#### `vault_search`

```json
{
  "name": "vault_search",
  "description": "FTS5 全文搜索 Vault 笔记。返回结构化匹配结果。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": { "type": "string" },
      "tags": { "type": "array", "items": { "type": "string" } },
      "project": { "type": "string" },
      "type": { "type": "string" },
      "limit": { "type": "integer", "default": 10 },
      "offset": { "type": "integer", "default": 0 }
    },
    "required": ["query"]
  }
}
```

#### `vault_resume`

```json
{
  "name": "vault_resume",
  "description": "读取项目的最近会话日志和架构决策笔记。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project": { "type": "string" },
      "log_count": { "type": "integer", "default": 3 }
    },
    "required": ["project"]
  }
}
```

### 管理工具 (P1)

#### `vault_list`

```json
{
  "name": "vault_list",
  "description": "按条件结构化列出笔记，支持分页和排序。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "tags": { "type": "array", "items": { "type": "string" }, "description": "按标签过滤" },
      "project": { "type": "string", "description": "按项目过滤" },
      "type": { "type": "string", "description": "按笔记类型过滤" },
      "status": { "type": "string", "description": "按状态过滤" },
      "sort": { "type": "string", "enum": ["created", "updated", "title"], "description": "排序字段" },
      "limit": { "type": "integer", "default": 20 },
      "offset": { "type": "integer", "default": 0 }
    }
  }
}
```

#### `vault_stats`

```json
{
  "name": "vault_stats",
  "description": "返回知识库统计面板：笔记总数、按类型/项目分布、Top 标签、最近新增、链接密度。",
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}
```

#### `vault_orphan`

```json
{
  "name": "vault_orphan",
  "description": "检测孤立笔记——没有被任何其他笔记引用（入度为0）或不引用任何笔记（出度为0）的笔记。",
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}
```

#### `vault_update`

```json
{
  "name": "vault_update",
  "description": "更新已有笔记的正文内容，保留原有 frontmatter 并更新 updated 日期。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "note_path": { "type": "string", "description": "笔记文件路径（相对于 vault_dir）" },
      "new_content": { "type": "string", "description": "替换正文（与 append_content 二选一）" },
      "append_content": { "type": "string", "description": "追加到正文末尾" },
      "vault_dir": { "type": "string", "description": "Vault 根目录路径，默认 ~/vault" }
    },
    "required": ["note_path"]
  }
}
```

#### `vault_tags`

```json
{
  "name": "vault_tags",
  "description": "返回所有已用标签及使用频次，支持标签模糊搜索。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "标签模糊搜索关键词" }
    }
  }
}
```

#### `vault_log`

```json
{
  "name": "vault_log",
  "description": "写入会话日志到 Vault。记录做了什么、决策、待办事项。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project": { "type": "string", "description": "项目名" },
      "summary": { "type": "string", "description": "做了什么" },
      "decisions": { "type": "array", "items": { "type": "string" }, "description": "决策列表" },
      "todos": { "type": "array", "items": { "type": "string" }, "description": "待办列表" }
    },
    "required": ["project", "summary"]
  }
}
```

### graphify 工具 (P1)

#### `graphify_build`

```json
{
  "name": "graphify_build",
  "description": "对当前项目构建代码图谱，调用 graphify CLI (tree-sitter AST) 生成模块笔记到 Vault。依赖 graphify CLI (pip install graphifyy)。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project": { "type": "string", "description": "项目名" },
      "project_dir": { "type": "string", "description": "项目根目录路径" },
      "force": { "type": "boolean", "default": true }
    },
    "required": ["project", "project_dir"]
  }
}
```

**实现要点：**
- 调用 `graphify update <project_dir> --force`，超时 120s
- 解析 `graphify-out/graph.json`，复制到 `~/vault/graphify/<project>/`
- 自动复制 `Index.md`，统计节点数/边数/社区数
- 记录构建元数据到 `graphify_builds` 表（含 git commit SHA）
- graphify CLI 未安装时返回友好提示，不影响核心功能

#### `graphify_status`

```json
{
  "name": "graphify_status",
  "description": "返回代码图谱构建状态：上次构建时间、节点数、边数、社区数。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project": { "type": "string" }
    },
    "required": ["project"]
  }
}
```

#### `graphify_query`

```json
{
  "name": "graphify_query",
  "description": "在代码图谱笔记中搜索符号（类/函数/方法），返回所属模块和调用关系。支持模糊匹配。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project": { "type": "string" },
      "symbol": { "type": "string", "description": "符号名，支持模糊匹配" },
      "fuzzy": { "type": "boolean", "default": true }
    },
    "required": ["project", "symbol"]
  }
}
```

**实现要点：**
- 在 `~/vault/graphify/<project>/` 下所有 .md 文件中搜索符号
- fuzzy 模式使用大小写不敏感的字符串包含匹配
- 返回匹配文件列表（标题 + 相对路径），最多 20 条

---

## 实施路线图

### Phase 1: MCP Server 骨架 + 核心工具 ✅ 已完成

**目标:** MCP Server 可启动，save/search/resume/init 可用

| # | 任务 | 复杂度 | 状态 |
|---|------|--------|------|
| 1.1 | 搭建 MCP Server Python 工程骨架 | 小 (2h) | ✅ |
| 1.2 | 实现 SQLite 数据层：`VaultDB` 类 + 6 表 + FTS5 trigram + 12 索引 | 中 (6h) | ✅ |
| 1.3 | 实现 `vault_init` — 幂等初始化 + CLAUDE.md 生成 | 中 (3h) | ✅ |
| 1.4 | 实现 `vault_save` — 校验 + auto-wikilink + 磁盘检查 + 冲突检测 + 索引 | 中 (8h) | ✅ |
| 1.5 | 实现 `vault_search` — FTS5 + BM25 + 多条件过滤 | 中 (4h) | ✅ |
| 1.6 | 实现 `vault_resume` — 项目上下文恢复 | 小 (3h) | ✅ |
| 1.7 | 实现 `vault_log` — 会话日志写入（含 timestamp 防冲突） | 小 (2h) | ✅ |
| 1.8 | 编写路由 Skill `~/.claude/skills/kb.md` | 小 (2h) | ✅ |
| 1.9 | 注册 MCP Server 到 Claude Code (`claude mcp add`) | 小 (1h) | ✅ |
| 1.10 | 单元测试：`test_db.py`（82 个）+ `test_vault_tools.py`（30 个） | 中 (6h) | ✅ |

**检查点:** ✅ 核心闭环完整可用

---

### Phase 2: 管理工具 + graphify 模块 ✅ 已完成

**目标:** 完整知识库管理 + 代码图谱

| # | 任务 | 复杂度 | 状态 |
|---|------|--------|------|
| 2.1 | 实现 `vault_tags` — 标签统计 + 模糊搜索 | 小 (2h) | ✅ |
| 2.2 | 实现 `vault_list` — 条件列表 + 分页排序 | 中 (3h) | ✅ |
| 2.3 | 实现 `vault_stats` — SQL 聚合统计面板 | 中 (3h) | ✅ |
| 2.4 | 实现 `vault_orphan` — wikilink 引用图 + 孤立检测 | 中 (4h) | ✅ |
| 2.5 | 实现 `vault_update` — 替换/追加 + 保留 frontmatter | 小 (2h) | ✅ |
| 2.6 | 实现 `graphify_build` — CLI 调用 + JSON 解析 → 图谱笔记 | 中 (5h) | ✅ |
| 2.7 | 实现 `graphify_status` — 构建状态查询 | 小 (1h) | ✅ |
| 2.8 | 实现 `graphify_query` — 符号搜索（模糊/精确） | 中 (3h) | ✅ |
| 2.9 | 更新路由 Skill 加入 graphify 和管理命令 | 小 (1h) | ✅ |
| 2.10 | 集成测试：`test_graphify_tools.py`（25 个）+ E2E（14 步） | 中 (4h) | ✅ |

**检查点:** ✅ 13 个 MCP 工具全部可用

---

### Phase 3: 打磨 + 文档 ✅ 已完成

**目标:** 稳定可靠，文档齐全

| # | 任务 | 复杂度 | 状态 |
|---|------|--------|------|
| 3.1 | 大 Vault 性能优化（FTS5 批量索引、增量更新） | 中 (3h) | ✅ |
| 3.2 | 错误处理增强（graphify 未安装降级提示等） | 小 (2h) | ✅ |
| 3.3 | MCP Server 完整测试套件（133+ 测试） | 大 (10h) | ✅ |
| 3.4 | 使用手册：命令参考 + 典型工作流示例 | 中 (3h) | ✅ |
| 3.5 | `~/vault/CLAUDE.md` 优化 | 小 (1h) | ✅ |
| 3.6 | 发布包制作（`release/` 目录 + install.sh/install.ps1） | 中 (4h) | ✅ |
| 3.7 | PRD 文档与实现对齐 | 中 (3h) | ✅ |

**检查点:** 可放心日常使用

---

### Phase 4: 远期规划

**目标:** 生态扩展与深度集成

| # | 任务 | 复杂度 | 优先级 |
|---|------|--------|--------|
| 4.1 | **增量索引** — 文件系统监控（watchdog），自动检测 .md 文件变更并增量更新 FTS5 | 中 (6h) | P1 |
| 4.2 | **Obsidian 实时同步** — 双向同步机制，Obsidian 中修改的笔记自动回写到 SQLite | 大 (10h) | P2 |
| 4.3 | **标签自动建议** — 基于笔记内容关键词规则自动推荐标签（纯规则，不依赖 AI） | 中 (4h) | P2 |
| 4.4 | **Git 自动同步** — Vault 纳入 Git 版本控制，`/kb save` 可选自动 commit | 小 (3h) | P2 |
| 4.5 | **跨 Vault 联邦搜索** — 支持多个 Vault 目录，统一搜索入口 | 中 (8h) | P3 |
| 4.6 | **语义搜索** — 集成本地 embedding 模型（如 all-MiniLM-L6-v2），支持语义相似度搜索 | 大 (12h) | P3 |
| 4.7 | **笔记质量评分** — 基于 wikilink 密度、更新频率、标签完整性等维度评分 | 小 (3h) | P3 |

---

### 总工时统计

| Phase | 任务数 | 预估工时 | 实际工时 | 状态 |
|-------|--------|----------|----------|------|
| Phase 1: MCP + 核心工具 | 10 | 37h | ~40h | ✅ 完成 |
| Phase 2: 管理 + graphify | 10 | 28h | ~30h | ✅ 完成 |
| Phase 3: 打磨 + 文档 | 7 | 17h | ~17h | ✅ 已完成 |
| Phase 4: 远期规划 | 7 | 46h | - | ⬜ 待规划 |
| **合计** | **34** | **128h** | **~87h** | |

约 5 周（单人业余时间，每天 2-3 小时）完成 Phase 1-3。

---

## 范围外

1. **Obsidian 客户端安装与配置** — 用户自行决定，非必需
2. **云端同步** — 用户自行用 Git/iCloud/Dropbox 同步 Vault 文件夹
3. **多人协作 Vault** — 纯个人知识库
4. **聊天自动归档流水线** — 依赖 `claude-extract` 第三方 CLI，后续独立评估
5. **AI 语义标签/摘要** — v1.0 用关键词规则，不依赖外部 AI API
6. **移动端** — 仅桌面端
7. **Obsidian 插件开发** — 只遵循标准 Markdown + wikilink

---

## 待解决问题与风险

### 待解决问题

**Q1: Vault 放哪里？**
- **建议:** `~/vault/`（即 `C:\Users\<username>\vault\`），和社区方案一致，Git Bash 路径兼容

**Q2: 与 Claude Code 内置记忆的关系？**
- 内置记忆（`.claude/projects/`）：项目级偏好、反馈、角色设定 — 继续用
- Vault（`~/vault/`）：跨项目知识、解决方案、学习笔记 — 新增
- 互补，不替代

**Q3: graphify CLI 依赖怎么处理？**
- 作为可选依赖，MCP Server 启动时检测是否安装
- 未安装时 `/kb graphify` 返回友好提示，不影响核心命令

**Q4: MCP Server 怎么随 Claude Code 启动？**
- 在 `~/.claude/mcp.json` 注册为 stdio 类型 MCP Server
- 或 `claude mcp add vault -- python ~/scripts/vault-mcp-server/server.py`

**Q5: 笔记用什么语言？**
- 中文为主，技术术语保留英文

### 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| graphify Windows 兼容性问题 | 中 | 中 | P1 可选模块，核心功能不依赖；提前本地验证 |
| SQLite FTS5 中文分词效果不佳 | 中 | 低 | FTS5 支持 CJK 分词（需编译选项），不满足则降级为 LIKE + 关键词 |
| MCP Server 进程稳定性 | 低 | 高 | 数据在 .md 文件中，Server 挂了数据不丢 |
| 万级笔记后 FTS5 性能下降 | 低 | 低 | BM25 百万级仍毫秒级，远超个人使用规模 |

---

## 验收检查点

### 检查点 1: Phase 1 完成时
- [ ] `vault_init` 一键创建完整 Vault 目录 + 模板 + 数据库
- [ ] `vault_save` 写入笔记，frontmatter 校验通过，wikilink 自动匹配
- [ ] `vault_search` FTS5 搜索返回 JSON，标签过滤正常
- [ ] `vault_resume` 定位项目日志返回正确内容
- [ ] 路由 Skill 正确分发命令到对应 MCP 工具
- [ ] MCP Server 注册后 Claude Code 可正常调用

### 检查点 2: Phase 2 完成时
- [ ] `vault_stats` 统计数字准确
- [ ] `vault_orphan` 正确检测孤立笔记
- [ ] `vault_list` 分页排序正常
- [ ] `graphify_build` 成功生成图谱笔记到 Vault
- [ ] `/kb search` 可检索到图谱笔记
- [ ] `graphify_query` 返回正确符号归属

### 检查点 3: Phase 3 完成时
- [ ] MCP Server 单元测试覆盖率 > 70%
- [ ] 使用手册含 3 个以上完整工作流示例
- [ ] graphify 未安装时降级提示友好
- [ ] 500+ 笔记下 `vault_search` < 100ms

---

*此文档面向 Vault MCP Server 开发。架构采用纯 MCP + 薄路由 Skill 方案，数据存储在 Markdown 文件中，索引和元数据由 SQLite 管理。graphify 模块作为 P1 可选组件提供代码结构图谱能力。*
