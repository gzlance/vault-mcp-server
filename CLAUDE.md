# Vault MCP Server

个人知识库 + 代码图谱统一 MCP 服务，基于 Obsidian Vault 构建，通过 MCP stdio 协议与 Claude Code 通信。

## 项目架构

```
server.py                    # MCP 入口：注册 13 个工具，stdio JSON-RPC 通信
├── tools/
│   ├── _shared.py           # 公共层：输入校验、JSON 响应封装、路径处理
│   ├── vault_tools.py       # 10 个核心+管理工具（init/save/search/resume/list/stats/orphan/update/tags/log）
│   └── graphify_tools.py    # 3 个代码图谱工具（build/status/query）
├── db.py                    # SQLite 数据层 (VaultDB 类，6 表 + FTS5 + 12 索引)
├── tests/
│   ├── test_db.py           # VaultDB 单元测试（~82 个）
│   ├── test_vault_tools.py  # 工具处理函数集成测试（~30 个）
│   ├── test_graphify_tools.py # 图谱工具测试（~25 个）
│   └── e2e_test.py          # 端到端流程测试（14 步）
└── release/                 # 发布包（含 install.sh / install.ps1 / 源码镜像）
```

### 分层架构

```
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

### 数据库设计（6 表）

| 表 | 用途 |
|----|------|
| `notes` | 笔记元数据（title, path, tags, type, project, status, checksum） |
| `notes_fts` | FTS5 全文索引（trigram 分词，BM25 排序） |
| `tag_index` | 标签频次统计（UPSERT 去重） |
| `wikilinks` | 双向引用图（source → target + context） |
| `graphify_builds` | 代码图谱构建历史 |
| `session_logs` | 会话日志记录 |

### 13 个 MCP 工具

**核心工具 (P0)：** `vault_init` / `vault_save` / `vault_search` / `vault_resume` / `vault_log`
**管理工具 (P1)：** `vault_list` / `vault_stats` / `vault_orphan` / `vault_update` / `vault_tags`
**图谱工具 (P1)：** `graphify_build` / `graphify_status` / `graphify_query`

### 关键设计决策

- **SQLite 使用标准库 `sqlite3`**，不引入 ORM。WAL 模式，Context Manager 管理事务。
- **图式隔离** — graphify CLI 通过 AST 静态解析产出 `graph.json`，服务端将 JSON 直接转存为 Markdown 笔记，不做结构化图形分析。
- **自动 wikilink 检测** — `vault_save` 扫描正文中已知笔记标题的纯文本出现，自动替换为 `[[wikilink]]` 格式。
- **幂等初始化** — `vault_init` 可安全重复调用，所有 DDL 使用 `IF NOT EXISTS`。
- **Windows 兼容** — 强制 `PYTHONIOENCODING=utf-8`，测试中使用 `_SharedVaultDB` 避免文件锁。

### Vault 目录结构

```
~/vault/
├── permanent/           # 通用知识笔记（permanent/solution/concept/tool）
├── templates/           # 笔记模板
├── logs/                # 全局会话日志
├── <project>/           # 项目笔记（architecture/features/data/logs/）
│   └── logs/
└── graphify/            # 代码图谱笔记
    └── <project>/
        ├── Index.md
        └── Community-*.md
```

## 常用命令

### 开发环境

```bash
# 安装依赖
pip install -r requirements.txt

# 手动启动 MCP Server（验证用）
PYTHONIOENCODING=utf-8 python server.py
```

### 测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 仅运行数据库层测试
python -m pytest tests/test_db.py -v

# 运行单文件并显示覆盖率
python -m pytest tests/test_vault_tools.py -v --cov=tools.vault_tools --cov-report=term-missing

# 运行端到端测试
python -m pytest tests/e2e_test.py -v

# 运行特定测试
python -m pytest tests/test_db.py::TestVaultDB::test_save_note -v
```

### 代码质量

```bash
# 格式化
black server.py db.py tools/ tests/

# 导入排序
isort server.py db.py tools/ tests/

# Lint 检查
ruff check server.py db.py tools/ tests/

# 类型检查
mypy server.py db.py tools/ --ignore-missing-imports

# 安全检查
bandit -r server.py db.py tools/
```

### 部署

```bash
# 安装到 Claude Code
claude mcp add vault -- python "D:/MyWord/vault-mcp-server/server.py"

# 验证注册
claude mcp list

# 首次初始化知识库（在 Claude Code 对话中）
/kb init
```

## 代码规范

- **Python 3.10+**，遵循 **PEP 8**
- 所有函数签名使用**类型注解**
- 使用 `black` 格式化，`isort` 排序导入，`ruff` lint
- 文件大小：200-400 行标准，800 行上限
- 函数大小：50 行上限
- 嵌套深度：不超过 4 层，优先使用提前返回
- **不可变性优先** — 创建新对象，不修改已有对象
- 注释使用**中文**
- 错误处理遵循 **fail fast** 原则，严禁吞异常
- 禁止硬编码配置（中间件地址、API 密钥等）

### 工具模块开发规范

新增 MCP 工具时遵循以下约定：

1. 在 `tools/` 下对应模块添加 `async def handle_xxx(arguments: dict) -> list[TextContent]:`
2. 调用 `_shared.check_required()` 校验必填参数
3. 使用 `_shared.json_reply()` 统一封装响应
4. 在 `server.py` 中注册 Tool schema 和分发路由
5. 在 `tests/` 中编写对应测试

### 测试规范

- 框架：**pytest**
- 最低覆盖率：**80%**
- 测试组织：
  - `test_db.py` → 数据库层单元测试
  - `test_vault_tools.py` → 知识库工具集成测试
  - `test_graphify_tools.py` → 图谱工具集成测试
  - `e2e_test.py` → 端到端流程
- 使用 `unittest.mock.patch` 隔离外部依赖（文件系统、graphify CLI）
- Windows 兼容要点：测试中使用单一数据库连接（`_SharedVaultDB`），避免 sqlite3 文件锁问题

## 开发环境配置

### 必需

| 工具 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | 运行环境 |
| mcp | >=1.0.0 | MCP 协议 SDK |
| pytest | 最新 | 测试框架 |
| pytest-cov | 最新 | 覆盖率 |

### 可选

| 工具 | 用途 |
|------|------|
| graphifyy | 代码图谱生成（tree-sitter AST 解析） |
| black | 代码格式化 |
| isort | 导入排序 |
| ruff | Lint 检查 |
| mypy | 类型检查 |
| bandit | 安全检查 |

### 编码注意事项

- **Windows 平台**：必须设置 `PYTHONIOENCODING=utf-8`，否则 GBK 默认编码导致中文乱码
- **Unix 语法使用**：终端为 Git Bash，路径和命令使用 Unix 风格
- **子进程**：`graphify_build` 通过 `subprocess.run()` 调用外部 CLI，需注意 PATH 配置
- **代理**：外网请求超时时可通过 `socks5://10.0.0.2:10808` 代理重试

## 关键文件索引

| 文件 | 行数 | 说明 |
|------|------|------|
| `server.py` | 269 | MCP 入口，工具注册与分发 |
| `db.py` | ~600 | SQLite 数据层完整实现 |
| `tools/vault_tools.py` | ~400 | 10 个知识库工具 |
| `tools/graphify_tools.py` | ~200 | 3 个图谱工具 |
| `tools/_shared.py` | 47 | 公共校验与响应函数 |
| `tests/test_db.py` | ~700 | 数据库层 82 个测试 |
| `tests/test_vault_tools.py` | ~350 | 工具层 30 个测试 |
| `tests/test_graphify_tools.py` | ~300 | 图谱 25 个测试 |
| `tests/e2e_test.py` | ~200 | 14 步端到端流程 |
