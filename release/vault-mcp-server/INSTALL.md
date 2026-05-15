# Vault MCP Server 安装指南

**版本:** 2.0 | **更新:** 2026-05-15

## 目录

1. [环境要求](#环境要求)
2. [安装步骤](#安装步骤)
3. [MCP 配置](#mcp-配置)
4. [验证](#验证)
5. [初始化 Vault](#初始化-vault)
6. [Skill 安装](#skill-安装)
7. [常见问题](#常见问题)

---

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.10+ | 推荐 3.12 |
| pip | 22+ | 随 Python 安装 |
| Git | 2.30+ | 仅 graphify 图谱功能需要 |
| graphify CLI | 0.7+ | 可选，代码图谱功能 |

**操作系统**：Windows 10+ / macOS 12+ / Linux

---

## 安装步骤

### 1. 获取源码

```bash
git clone <repo-url> ~/scripts/vault-mcp-server
cd ~/scripts/vault-mcp-server
```

确保目录包含以下文件：
```
server.py
db.py                          # 向后兼容重导出（1 行）
db/
  __init__.py                  # VaultDB 外观类
  base.py                      # 连接管理 + 迁移
  notes.py                     # 笔记 CRUD + FTS5
  todos.py                     # 待办 CRUD
  session.py                   # 会话日志
  graph.py                     # 图谱构建记录
  wikilinks.py                 # 引用图
services/
  wikilink.py                  # wikilink 检测
  validator.py                 # 内容校验
  tags.py                      # 标签重叠检测
  resolver.py                  # 标题 → 路径三级解析
tools/
  _shared.py                   # get_project + 校验
  vault_init.py                # 初始化
  vault_save.py                # 保存笔记
  vault_search.py              # 搜索
  vault_resume.py              # 恢复上下文
  vault_list.py                # 列出笔记
  vault_stats.py               # 统计
  vault_orphan.py              # 孤立笔记
  vault_update.py              # 更新笔记
  vault_tags.py                # 标签列表
  vault_log.py                 # 会话日志
  vault_delete.py              # 删除笔记
  vault_todo_list.py           # 列出待办
  vault_todo_done.py           # 标记完成
  vault_todo_progress.py       # 标记进行中
  vault_todo_pending.py        # 恢复待处理
  vault_todo_delete.py         # 删除待办
  graphify_tools.py            # 代码图谱 (3 个工具)
  vault_tools.py               # 向后兼容重导出
skills/                         # 21 个 skill 文件
tests/                          # 8 个测试文件
```

### 2. 安装 Python 依赖

```bash
cd ~/scripts/vault-mcp-server
pip install -r requirements.txt
```

依赖：`mcp>=1.0.0`（必需），`graphifyy`（可选）。

### 3. 验证模块导入

```bash
cd ~/scripts/vault-mcp-server
PYTHONIOENCODING=utf-8 python -c "
from db import VaultDB
from tools.vault_save import handle_save
from tools.vault_delete import handle_delete
from tools.vault_todo_list import handle_todo_list
from services.resolver import resolve_title_to_path
from tools.graphify_tools import handle_graphify_status
print('所有模块导入成功')
"
```

### 4. 运行测试

```bash
pip install pytest -q
cd ~/scripts/vault-mcp-server
PYTHONIOENCODING=utf-8 python -m pytest tests/ -v
```

预期输出：`259 passed`，覆盖率 89%。

---

## MCP 配置

### 配置文件: `~/.claude/mcp.json`

**Windows：**
```json
{
  "mcpServers": {
    "vault": {
      "command": "python",
      "args": ["C:\\Users\\<用户名>\\scripts\\vault-mcp-server\\server.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

**macOS / Linux：**
```json
{
  "mcpServers": {
    "vault": {
      "command": "python3",
      "args": ["/home/<用户名>/scripts/vault-mcp-server/server.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

| 配置项 | 说明 |
|--------|------|
| Windows 路径 | 必须用双反斜杠 `\\` 或单正斜杠 `/` |
| PYTHONIOENCODING | **必须设为 utf-8**，否则中文乱码 |
| command | 如果 python 不在 PATH，用完整路径 |

保存后**完全退出并重启 Claude Code**。

---

## 验证

### 命令行验证

```bash
cd ~/scripts/vault-mcp-server
PYTHONIOENCODING=utf-8 python tests/e2e_test.py -v
```

### Claude Code 中验证

```
/kb-stats
```

---

## 初始化 Vault

```
/kb-init
```

产物：
```
~/vault/
├── vault.db                # SQLite 索引
├── permanent/              # 永久知识
├── templates/              # 笔记模板
├── logs/                   # 全局日志
├── graphify/               # 代码图谱
└── <project>/              # 项目笔记
    ├── architecture/
    ├── features/
    ├── data/
    └── logs/
```

---

## Skill 安装

v2.0 提供 21 个独立 Skill 文件。安装脚本自动部署到 `~/.claude/skills/`：

```bash
# 自动安装（推荐）
bash release/install.sh

# 手动复制
cp -r skills/* ~/.claude/skills/
```

### 命令清单（21 个）

| 命令 | 说明 |
|------|------|
| `/kb` | 帮助面板 |
| `/kb-init` | 初始化 |
| `/kb-save` | 保存笔记 |
| `/kb-search <关键词>` | 全文搜索 |
| `/kb-resume` | 恢复上下文 |
| `/kb-list` | 列出笔记 |
| `/kb-stats` | 统计面板 |
| `/kb-tags` | 标签列表 |
| `/kb-orphan` | 孤立笔记 |
| `/kb-update <标题>` | 更新笔记 |
| `/kb-delete <标题>` | 删除笔记 |
| `/kb-learn` | 学习记录 |
| `/kb-log <摘要>` | 会话日志 |
| `/kb-todo-list` | 列出待办 |
| `/kb-todo-done <id>` | 标记完成 |
| `/kb-todo-progress <id>` | 标记进行中 |
| `/kb-todo-pending <id>` | 恢复待处理 |
| `/kb-todo-delete <id>` | 删除待办 |
| `/kb-graph-build` | 构建图谱 |
| `/kb-graph-status` | 图谱状态 |
| `/kb-graph-query <符号>` | 搜索符号 |

---

## 常见问题

### Q1: "No module named mcp"
```bash
pip install mcp>=1.0.0
```

### Q2: Windows 中文乱码
检查 `mcp.json` 中 `"PYTHONIOENCODING": "utf-8"`。

### Q3: 中文搜索无结果
删除旧数据库重建：`rm ~/.vault-mcp/vault.db`，然后 `/kb-init`。

### Q4: graphify 构建失败
```bash
pip install graphifyy
```

### Q5: MCP Server 未加载
检查 `mcp.json` JSON 语法，确认 Python 版本 ≥ 3.10。

### Q6: 升级到 v2.0
```bash
cd ~/scripts/vault-mcp-server
git pull
pip install -r requirements.txt --upgrade
cp -r skills/* ~/.claude/skills/
PYTHONIOENCODING=utf-8 python -m pytest tests/ -q
```
