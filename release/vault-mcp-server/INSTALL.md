# Vault MCP Server 安装指南

## 目录

1. [环境要求](#环境要求)
2. [安装步骤](#安装步骤)
3. [MCP 配置](#mcp-配置)
4. [验证](#验证)
5. [初始化 Vault](#初始化-vault)
6. [Skill 安装](#skill-安装可选)
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
# 如果使用 Git
git clone <repo-url> ~/scripts/vault-mcp-server
cd ~/scripts/vault-mcp-server

# 或者直接下载并解压到 ~/scripts/vault-mcp-server/
```

确保目录包含以下文件：
```
server.py
db.py
requirements.txt
tools/
  __init__.py
  _shared.py
  vault_tools.py
  graphify_tools.py
tests/
  test_db.py
  test_vault_tools.py
  test_graphify_tools.py
  e2e_test.py
```

### 2. 安装 Python 依赖

```bash
cd ~/scripts/vault-mcp-server
pip install -r requirements.txt
```

依赖内容：
- `mcp>=1.0.0` — MCP 协议 Python SDK（必需）
- `graphifyy` — 代码图谱 CLI（可选，安装失败不影响核心功能）

如果不需要代码图谱功能，可以只装核心依赖：
```bash
pip install mcp>=1.0.0
```

### 3. 验证模块导入

```bash
cd ~/scripts/vault-mcp-server
PYTHONIOENCODING=utf-8 python -c "
from db import VaultDB
from tools.vault_tools import handle_init, handle_save, handle_search
from tools.graphify_tools import handle_graphify_status
print('所有模块导入成功')
"
```

### 4. 运行测试（推荐）

```bash
pip install pytest -q
cd ~/scripts/vault-mcp-server
PYTHONIOENCODING=utf-8 python -m pytest tests/ -v
```

预期输出：`211 passed`，耗时约 12 秒。

---

## MCP 配置

### 配置文件位置

`~/.claude/mcp.json`

Windows 实际路径：`C:\Users\<用户名>\.claude\mcp.json`

### 添加 Vault MCP Server

在 `mcpServers` 中添加：

**Windows：**
```json
{
  "mcpServers": {
    "vault": {
      "command": "python",
      "args": ["C:\\Users\\<用户名>\\scripts\\vault-mcp-server\\server.py"],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
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
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### 注意事项

| 配置项 | 说明 |
|--------|------|
| Windows 路径 | 必须用双反斜杠 `\\` 或单正斜杠 `/` |
| PYTHONIOENCODING | **必须设为 `utf-8`**，否则 Windows 下中文乱码 |
| command | 如果 `python` 不在 PATH，用完整路径如 `D:\\Program Files\\Python\\Python312\\python.exe` |
| JSON 语法 | 最后一个花括号前不能有多余逗号 |

### 生效

保存 `mcp.json` 后，**完全退出并重启 Claude Code**。

---

## 验证

### 方法一：命令行验证

```bash
cd ~/scripts/vault-mcp-server
PYTHONIOENCODING=utf-8 python -c "
import asyncio, json, subprocess, sys, os

async def verify():
    proc = subprocess.Popen(
        [sys.executable, 'server.py'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
        encoding='utf-8',
    )

    # MCP 握手
    proc.stdin.write(json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'test', 'version': '1.0'}
        }
    }) + '\n')
    proc.stdin.flush()
    server = json.loads(proc.stdout.readline())['result']['serverInfo']
    print(f'Server: {server[\"name\"]} v{server[\"version\"]}')

    # 通知
    proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
    proc.stdin.flush()

    # 列出工具
    proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}) + '\n')
    proc.stdin.flush()
    tools = json.loads(proc.stdout.readline())['result']['tools']
    print(f'注册工具: {len(tools)} 个')
    for t in tools:
        print(f'  - {t[\"name\"]}')

    proc.stdin.close(); proc.wait(timeout=3)
    print('\n验证通过')

asyncio.run(verify())
"
```

预期输出：
```
Server: vault-mcp v1.27.1
注册工具: 13 个
  - vault_init
  - vault_save
  - vault_search
  - vault_resume
  - vault_list
  - vault_stats
  - vault_orphan
  - vault_update
  - vault_tags
  - vault_log
  - graphify_build
  - graphify_status
  - graphify_query

验证通过
```

### 方法二：在 Claude Code 中验证

重启后输入：

```
/kb stats
```

如果返回统计信息，说明服务正常。

---

## 初始化 Vault

### 在 Claude Code 中初始化

```
初始化知识库
```

或指定项目：

```
初始化知识库，项目名是 backend-tools
```

### 或用命令行直接初始化

```bash
cd ~/scripts/vault-mcp-server
PYTHONIOENCODING=utf-8 python -c "
import asyncio, json
from tools.vault_tools import handle_init

r = asyncio.run(handle_init({'project': 'my-project'}))
print(json.loads(r[0].text))
"
```

### 初始化产物

```
~/vault/
├── CLAUDE.md               # Vault 使用规则
├── vault.db                # SQLite 索引（自动生成）
├── permanent/              # 永久知识笔记
├── templates/
│   ├── default-note.md     # 通用模板
│   └── session-log.md      # 会话日志模板
├── logs/                   # 全局会话日志
├── graphify/               # 代码图谱笔记
└── <project>/              # 项目笔记（如指定了 --project）
    ├── architecture/
    ├── features/
    ├── data/
    └── logs/
```

---

## Skill 安装（可选）

`/kb` 路由 Skill 提供命令别名，让你用自然语言触发工具。

### 安装

```bash
mkdir -p ~/.claude/skills/kb
```

将 Skill 文件放入 `~/.claude/skills/kb/SKILL.md`。

**注意：** 文件名必须是 `SKILL.md`，且放在 `skills/kb/` 子目录中。扁平放 `skills/kb.md` 不会被识别。

### 命令列表

| 命令 | 触发方式 |
|------|---------|
| `/kb init` | "初始化知识库" |
| `/kb save` | "保存到知识库"、"记住这个" |
| `/kb search <词>` | "搜索知识库 xxx" |
| `/kb resume <项目>` | "恢复 xxx 上下文" |
| `/kb stats` | "知识库统计" |
| `/kb list` | "列出笔记" |
| `/kb orphan` | "找孤立笔记" |
| `/kb tags` | "标签列表" |
| `/kb log` | "写工作日志" |
| `/kb update` | "更新笔记" |
| `/kb graphify build` | "构建代码图谱" |
| `/kb graphify status` | "图谱状态" |
| `/kb graphify query <符号>` | "搜索符号 xxx" |

---

## 常见问题

### Q1: "No module named mcp"

```bash
pip install mcp>=1.0.0
```

### Q2: Windows 中文乱码

检查 `mcp.json` 中是否设置了：
```json
"env": { "PYTHONIOENCODING": "utf-8" }
```

### Q3: 中文搜索无结果

旧版本数据库使用默认分词器，中文支持差。删除数据库重建：
```bash
rm ~/.vault-mcp/vault.db
```
然后重新运行 `vault_init`。

### Q4: graphify 构建失败

`graphifyy` 是可选依赖，不影响核心功能。需要时：
```bash
pip install graphifyy
git --version  # 确认 Git 已安装
```

### Q5: MCP Server 未加载

1. 检查 `mcp.json` JSON 语法（多余逗号最常见）
2. 确认 Python 路径：`python --version`
3. 看 `~/.claude/logs/` 中的日志

### Q6: "database is locked"

SQLite WAL 模式一般不会出现。如果出现：
```bash
rm ~/.vault-mcp/vault.db-wal ~/.vault-mcp/vault.db-shm
```

### Q7: `/kb` 命令无效

确认 Skill 文件位置正确：
```
~/.claude/skills/kb/SKILL.md   ← 正确
~/.claude/skills/kb.md         ← 错误
```

### Q8: 升级

```bash
cd ~/scripts/vault-mcp-server
git pull
pip install -r requirements.txt --upgrade
PYTHONIOENCODING=utf-8 python -m pytest tests/ -q
```
