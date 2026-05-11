# Vault MCP Server

个人知识库 + 代码图谱统一 MCP 服务。

**最后更新:** 2026-05-10
**Python:** 3.10+
**协议:** MCP stdio

---

## 项目概述

Vault MCP Server 基于 Obsidian Vault 构建统一个人知识库，通过 MCP 协议与 Claude Code 深度集成。工作或学习中解决的问题、学到的知识，一句话就能按模板持久化为 Markdown 笔记，后续在任何项目中都能全文检索复用。

核心能力：

- **结构化存储** — Markdown + YAML frontmatter，文件名 kebab-case，使用 Obsidian `[[wikilink]]` 格式链接笔记
- **全文索引** — SQLite FTS5 + BM25 相关度排序，覆盖 permanent/、project/、graphify/ 全部目录
- **代码图谱** — graphify CLI（tree-sitter AST）自动提取代码结构，生成可浏览的模块笔记
- **上下文恢复** — 读取项目会话日志和架构决策笔记，快速恢复工作状态
- **引用图分析** — 追踪 wikilink 引用关系，检测孤立笔记

架构分层：

```
Claude Code  ──MCP──>  Vault MCP Server  ──SQLite──>  ~/vault/ (.md 笔记文件)
    |                       |
    |  /kb 路由指令          ├── vault_init/save/search/resume/list/stats/orphan/update/tags/log
    |  (~/.claude/skills/    └── graphify_build/status/query
    |   kb.md)
    |
    └── (可选) Obsidian 客户端 ──> 知识图谱可视化浏览
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install mcp>=1.0.0
# graphify 为可选依赖，用于代码图谱功能
pip install graphifyy
```

### 2. 启动 MCP Server（手动验证）

```bash
PYTHONIOENCODING=utf-8 python C:/Users/Gzlance/scripts/vault-mcp-server/server.py
```

### 3. 注册到 Claude Code

编辑 `~/.claude/mcp.json`：

```json
{
  "mcpServers": {
    "vault": {
      "command": "python",
      "args": [
        "C:/Users/Gzlance/scripts/vault-mcp-server/server.py"
      ],
      "type": "stdio",
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

注册后可用 MCP 命令验证：

```bash
claude mcp list
claude mcp add vault -- python C:/Users/Gzlance/scripts/vault-mcp-server/server.py
```

### 4. 初始化知识库

首次使用需要初始化 Vault 目录结构和 SQLite 数据库：

```bash
# 对 Claude Code 说
初始化知识库

# 或指定项目目录
/kb init --project myproject
```

---

## 命令参考

共 13 个 MCP 工具，分为核心工具、管理工具和代码图谱工具三类。

### 核心工具 (P0)

| 工具名 | 功能 | 必填参数 | 说明 |
|--------|------|----------|------|
| `vault_init` | 初始化 Vault 目录 + 模板 + SQLite | 无 | 幂等操作，已初始化部分自动跳过 |
| `vault_save` | 保存知识笔记 | `title`, `content`, `tags`, `type` | 自动匹配已有笔记生成 `[[wikilink]]`，写入 .md 并更新 FTS5 索引 |
| `vault_search` | FTS5 全文搜索 | `query` | 返回标题、片段高亮、标签、相关度分数，支持按 tag/project/type 过滤 |
| `vault_resume` | 恢复项目工作上下文 | `project` | 读取最近 N 个会话日志 + 架构决策笔记 |
| `vault_log` | 写入会话日志 | `project`, `summary` | 记录做了什么、决策、待办事项 |

### 管理工具 (P1)

| 工具名 | 功能 | 必填参数 | 说明 |
|--------|------|----------|------|
| `vault_list` | 条件列表查询 | 无 | 支持按 tag/project/type/status 过滤，分页排序 |
| `vault_stats` | 知识库统计面板 | 无 | 笔记总数、类型分布、Top 标签、链接密度 |
| `vault_orphan` | 孤立笔记检测 | 无 | 找出入度为 0 或出度为 0 的笔记 |
| `vault_update` | 更新已有笔记 | `note_path` | 替换或追加正文，保留 frontmatter，更新索引 |
| `vault_tags` | 标签索引查询 | 无 | 返回所有已用标签及使用频次，支持模糊搜索 |

### 代码图谱工具 (P1)

| 工具名 | 功能 | 必填参数 | 说明 |
|--------|------|----------|------|
| `graphify_build` | 构建代码图谱 | `project`, `project_dir` | 调用 graphify CLI 解析 AST，生成模块笔记到 Vault |
| `graphify_status` | 图谱构建状态 | `project` | 上次构建时间、节点数、边数、社区数 |
| `graphify_query` | 代码符号搜索 | `project`, `symbol` | 在 graph.json 中模糊匹配符号，返回所属模块 |

### 笔记类型

| type | 用途 | 存放位置 |
|------|------|----------|
| `permanent` | 永不删除的原子知识笔记 | `~/vault/permanent/` |
| `solution` | 技术问题解决方案 | `~/vault/permanent/` 或 `~/vault/<project>/` |
| `concept` | 概念解释 | `~/vault/permanent/` |
| `tool` | 工具使用技巧 | `~/vault/permanent/` |
| `session-log` | 会话日志（自动归入 logs/） | `~/vault/logs/` 或 `~/vault/<project>/logs/` |
| `code-graph` | 代码图谱笔记（自动生成） | `~/vault/graphify/<project>/` |

---

## 典型工作流

### 工作流 1: 解决问题后保存

```
用户: "git push 总是失败，报 permission denied"

Claude 排查并解决问题...

用户: "把这个解决方案保存到知识库"
```

Claude 执行流程：

1. 回顾对话，提取问题背景、解决方案、关键命令
2. 确定 `title`（如 "Git 推送权限被拒的排查步骤"）
3. 确定 `tags`（如 `["git", "ssh", "permission"]`）和 `type: solution`
4. 构建 Markdown 正文，手动添加或让系统自动生成 `[[wikilink]]`
5. 调用 `vault_save`（服务端会自动检测正文中出现的已知笔记标题，替换为 `[[wikilink]]` 格式）
6. 返回结果：`created → permanent/git-tui-shen-quan-xian-bei-ju-de-pai-cha-bu-zhou.md | wikilinks: 3`

> **自动 wikilink 机制:** `vault_save` 在保存时自动扫描正文，将已知笔记标题的纯文本出现替换为 `[[标题]]` 格式，无需手动添加链接。

### 工作流 2: 搜索复用知识

```
用户: "之前那个 Windows 下 subprocess 编码问题的解决方案还在吗？"

# 或直接用命令
/kb search Windows subprocess 编码
```

Claude 调用 `vault_search`，参数 `{"query": "Windows subprocess 编码"}`，返回结构化结果：

```json
{
  "status": "ok",
  "query": "Windows subprocess 编码",
  "count": 3,
  "results": [
    {
      "title": "Windows Python subprocess 乱码解决方案",
      "snippet": "...设置 <b>PYTHONIOENCODING</b>=utf-8...",
      "tags": ["windows", "python", "encoding"],
      "type": "solution",
      "score": 0.87
    }
  ]
}
```

用户可直接在对话中引用笔记内容，Claude 自动应用其中的方案。

### 工作流 3: 恢复工作上下文

```
用户: "继续昨天 myproject 的工作"

# 或
/kb resume myproject
```

Claude 调用 `vault_resume`，参数 `{"project": "myproject", "log_count": 3}`，返回：

- 最近 3 篇会话日志（含做了什么、决策、待办）
- 最近 5 篇架构决策笔记

Claude 用自然语言总结：

> 上次你在 myproject 做了以下工作：
> 1. 实现了 MCP Server 的核心工具 save/search/resume
> 2. 决策：SQLite 用标准库 sqlite3，不引入 ORM
> 3. 待办：补充单元测试、完善错误处理
>
> 需要我帮你继续其中某件事吗？

---

## 目录结构

### Vault MCP Server 源码

```
~/scripts/vault-mcp-server/
├── server.py                  # MCP 入口，注册 13 个工具，stdio 通信
├── db.py                      # SQLite 数据库层 (VaultDB 类)
├── requirements.txt           # mcp>=1.0.0, graphifyy (可选)
├── tools/
|   ├── __init__.py
|   ├── _shared.py             # 公共工具: 输入校验、JSON 回复、路径处理
|   ├── vault_tools.py         # 10 个核心 + 管理工具实现
|   └── graphify_tools.py      # 3 个代码图谱工具实现
└── tests/                     # 单元测试
```

### Vault 知识库

```
~/vault/                       # Obsidian Vault 根目录
├── CLAUDE.md                  # Vault 使用规则（笔记规范 + 三层查询策略）
├── permanent/                 # 永久知识笔记 (type: permanent/solution/concept)
├── templates/
|   ├── default-note.md        # 通用笔记模板
|   └── session-log.md         # 会话日志模板
├── logs/                      # 全局会话日志 (type: session-log)
├── <project>/                 # 项目笔记（每个项目一个子目录）
|   ├── architecture/          # 架构决策笔记
|   ├── features/              # 功能笔记
|   ├── data/                  # 数据模型笔记
|   └── logs/                  # 项目会话日志
└── graphify/                  # 代码图谱笔记
    └── <project>/
        ├── Index.md           # 图谱索引
        └── Community-*.md     # 按社区（模块）分类的代码笔记
```

### Claude Code 配置

```
~/.claude/
├── skills/
|   └── kb.md                  # /kb 路由指令（薄 Skill，~40 行）
└── mcp.json                   # MCP Server 注册配置
```

---

## 常见问题

### graphify CLI 未安装

graphify 是可选依赖，未安装时不影响核心知识库功能。如果运行 `/kb graphify build` 时提示未安装：

```bash
pip install graphifyy
```

如果安装后仍报 "graphify CLI 未安装"，检查 PATH 是否正确，或使用完整路径：

```bash
# 查看 graphify 安装位置
pip show graphifyy | grep Location
```

### 中文搜索效果不佳

SQLite FTS5 默认使用空格分词，对中文（无空格分隔）效果可能不理想。当前方案：
- 短关键词（2-3 字）可精确匹配
- 长句搜索建议用关键词组合而非完整句子
- 标题精确匹配不受分词影响

Vault MCP Server 已配置 `PYTHONIOENCODING=utf-8`，确保中文内容读写无乱码。

### Windows 编码问题

在 Windows 上如果遇到 GBK 编码错误，确保：
1. 环境变量 `PYTHONIOENCODING=utf-8` 已设置
2. MCP Server 启动命令中已包含 `"env": {"PYTHONIOENCODING": "utf-8"}`
3. 所有 .md 文件以 UTF-8 编码写入

### MCP Server 启动失败

```bash
# 检查 Python 版本 (需要 3.10+)
python --version

# 检查 mcp 包是否安装
pip show mcp

# 手动启动测试
python C:/Users/Gzlance/scripts/vault-mcp-server/server.py
# 如果无报错退出，说明 MCP stdio 正常启动
```

### 笔记保存后搜索不到

`vault_save` 同步写入 .md 文件和 SQLite 索引。如果搜索不到，检查：
1. `~/vault/` 下对应的 .md 文件是否存在
2. SQLite 数据库是否损坏：删除 `~/vault/.vault.db` 后重新运行 `vault_init`（不影响已有的 .md 文件）

### Vault 目录在哪里

默认 `~/vault/`，即 `C:\Users\<你的用户名>\vault\`。可在每次调用时通过 `vault_dir` 参数覆盖，或在 `~/.claude/mcp.json` 中通过环境变量 `VAULT_DIR` 指定。

---

## 相关文档

- PRD 与完整规格: `D:\MyWord\claudeTest\docs\prd-knowledge-base.md`
- 路由 Skill: `~/.claude/skills/kb.md`
- Obsidian Vault 社区方案: [wangjun.dev](https://www.wangjun.dev/2026/05/claude-code-memory-setup/)
