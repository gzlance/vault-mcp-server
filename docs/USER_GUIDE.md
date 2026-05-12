# Vault MCP Server 使用手册

**版本:** 1.0 | **更新:** 2026-05-11 | **目标用户:** Claude Code 用户

---

## 1. 快速开始

### 1.1 前置条件

| 依赖 | 必选 | 说明 |
|------|------|------|
| Python 3.10+ | 是 | MCP Server 运行环境 |
| mcp >=1.0.0 | 是 | MCP 协议 SDK (`pip install mcp`) |
| graphifyy | 否 | 代码图谱功能 (`pip install graphifyy`) |
| Claude Code | 是 | MCP 宿主，通过 `/kb` 指令交互 |

### 1.2 安装与注册

**方式 1：一键安装脚本（推荐）**

```bash
# Windows
powershell -ExecutionPolicy Bypass -File release/install.ps1

# Linux/macOS
bash release/install.sh
```

脚本自动完成：文件复制、pip 依赖安装、MCP 配置写入 `~/.claude.json`、`/kb` Skill 安装。

**方式 2：手动安装**

```bash
# 1. 安装依赖
pip install mcp>=1.0.0

# 2. 编辑 ~/.claude.json，在 mcpServers 中添加：
# {
#   "mcpServers": {
#     "vault": {
#       "command": "python",
#       "args": ["~/scripts/vault-mcp-server/server.py"],
#       "env": { "PYTHONIOENCODING": "utf-8" }
#     }
#   }
# }
```

**验证注册：**

在 Claude Code 中输入 `/kb stats`，返回统计面板即注册成功。也可用 `claude mcp list` 查看 MCP 服务列表。

> **Windows 用户:** MCP 配置中必须设置 `PYTHONIOENCODING=utf-8`，否则中文乱码。PyPI 包名为 `mcp`（非 `mcp-server`）。

### 1.3 首次初始化

在 Claude Code 对话中输入 `/kb init`。Claude 自动完成：
- 创建 `~/vault/` 目录结构（permanent/、templates/、logs/、graphify/）
- 生成笔记模板和 SQLite 数据库（6 表 + FTS5 全文索引）

也可指定项目：`/kb init --project myproject`。**幂等操作**，重复运行安全。

---

## 2. 命令参考

全部 13 个 MCP 工具，通过 `/kb` 路由触发，按 P0 到 P1 排序。

### 核心命令 (P0)

#### /kb init
**功能:** 初始化 Vault 目录 + 模板 + SQLite。幂等。  
**参数:** `--project`（可选，初始化项目子目录）

> 用户: 初始化知识库  
> Claude: 已完成。创建 permanent/ logs/ graphify/ 目录，6 表 FTS5 数据库就绪。

---

#### /kb save
**功能:** 保存知识笔记，自动匹配已有笔记生成 `[[wikilink]]`。  
**参数:** title(必填)、content(必填)、tags(必填)、type(必填)、project(可选)、status(可选，默认 draft)

> 用户: 把刚才那个 Windows 编码问题的解决方案保存到知识库  
> Claude: 已保存。标题: Windows Python subprocess 中文乱码解决方案。类型: solution。标签: [windows, python, encoding]。3 个 wikilink 已自动生成。

---

#### /kb search
**功能:** FTS5 + BM25 全文检索，返回标题、高亮片段、相关度分数。  
**参数:** query(必填)、`--tag`、`--project`、`--type`、`--limit`(默认10)

> 用户: 搜索 Windows 编码问题的笔记  
> Claude: 找到 3 条。1. Windows Python subprocess 乱码方案 (score:0.87) | 2. Git Bash 编码配置 (score:0.72)...

---

#### /kb resume
**功能:** 读取项目最近会话日志 + 架构笔记，恢复工作上下文。  
**参数:** project(必填)、log_count(可选，默认3)

> 用户: /kb resume vault-mcp-server  
> Claude: 上次你做了: 1. graphify_build 工具实现。决策: graphify 作为可选依赖。待办: 编写 E2E 测试...

---

#### /kb learn
**功能:** 学习记录，实际调用 `vault_save`，默认 type: concept，status: draft。  
**参数:** 同 `/kb save`

> 用户: /kb learn Docker 多阶段构建可以大幅减小镜像体积，原理是...  
> Claude: 已保存。标题: Docker 多阶段构建减小镜像体积。状态: draft。

---

### 管理命令 (P1)

#### /kb list
**功能:** 条件列表查询，支持分页排序。  
**参数:** `--tag`、`--project`、`--type`、`--status`、`--sort`(created/updated/title)、`--limit`(默认20)、`--offset`

> 用户: /kb list --project vault-mcp-server --status draft  
> Claude: 3 条草稿笔记: SQLite WAL 性能测试 | Windows 文件锁方案 | 协程异常处理模式

---

#### /kb stats
**功能:** 知识库统计面板（总数、分布、Top 标签、链接密度）。无必填参数。

> 用户: /kb stats  
> Claude: 总笔记 47 篇。permanent(12) solution(18) concept(10) tool(4) log(3)。Top 标签: python(22) windows(15)。平均链接密度: 1.89/篇。

---

#### /kb orphan
**功能:** 检测入度=0 或出度=0 的孤立笔记。无必填参数。

> 用户: /kb orphan  
> Claude: 入度0有5篇(未被引用): MySQL慢查询、VS Code快捷键... | 出度0有8篇(无链接)。建议补充 [[wikilink]]。

---

#### /kb update
**功能:** 更新笔记正文，替换或追加，保留 frontmatter。  
**参数:** note_path(必填)、new_content(替换) 或 append_content(追加)

> 用户: 把 "Windows 编码问题" 笔记补充 gbk 编码的 case  
> Claude: 已追加 234 字到 Windows Python subprocess 乱码解决方案。

---

#### /kb tags
**功能:** 查看所有标签及频次，支持模糊搜索。

> 用户: /kb tags py  
> Claude: 匹配: python(22), pytest(3), pypi(1)

---

#### /kb log
**功能:** 写入会话日志（做了什么、决策、待办）。  
**参数:** project(必填)、summary(必填)、decisions(可选)、todos(可选)

> 用户: 记录一下今天进度  
> Claude: 已写入。做了什么: 完成 E2E 测试。决策: 采用 pytest 统一框架。待办: 编写使用手册。

---

### 代码图谱命令 (P1)

> 需 `pip install graphifyy`。未安装时友好降级提示。

#### /kb graphify build
**功能:** AST 解析项目代码，生成模块笔记到 `~/vault/graphify/<project>/`。  
**参数:** project(必填)、project_dir(必填)、force(默认true)

> 用户: 分析一下 vault-mcp-server 的项目结构  
> Claude: 18 源文件解析完成 -> 15 个模块。生成 Index.md + Community-*.md，构建耗时 8.5 秒。

---

#### /kb graphify status
**功能:** 查看上次构建时间、节点数、边数、社区数。  
**参数:** project(必填)

> 用户: /kb graphify status vault-mcp-server  
> Claude: 节点42 边87 社区5。上次构建: 2026-05-11。与 commit 3f8a12b 一致。

---

#### /kb graphify query
**功能:** 在代码图谱中搜索符号（类/函数/方法），返回所属模块和调用关系。  
**参数:** project(必填)、symbol(必填)、fuzzy(默认true)

> 用户: 查 VaultDB 类被哪些模块调用  
> Claude: db.py::VaultDB -> Community-DataLayer。被调用: vault_tools.py(5次), graphify_tools.py(2次)。

---

## 3. 典型工作流

### 工作流 1: 新项目上手

```
/kb init --project myproject          # 1. 初始化项目目录
/kb graphify build myproject D:/code  # 2. 构建代码图谱
帮我看看项目模块划分                    # 3. Claude 基于 graphify_status 列出模块职责
UserController 在哪个模块？            # 4. graphify_query 定位符号
在 UserController 中加个接口            # 5. Claude 已知位置，直接修改
```

**效果:** 不熟悉的项目，5 分钟内建立架构认知。

---

### 工作流 2: 每日工作循环

```
/kb resume myproject                   # 开始: 总结昨天做了什么、决策、待办
  (工作中遇到问题) 这个 Redis 锁方案之前查过吗？
  Claude: vault_search "Redis 分布式锁" -> 返回保存的方案
记录今天的进展                          # 结束: vault_log 写入会话日志
```

**效果:** 每天有始有终，上下文无缝衔接。

---

### 工作流 3: 解决问题后沉淀

```
Git push 报 Permission denied...       # 排查问题
先搜一下有没有 git push 的笔记           # vault_search 验证是否重复
把这个解决方案保存到知识库               # vault_save -> 标题、标签、自动 wikilink
/kb search git push                    # 验证: score 0.95，可复用了
```

**效果:** 三句话沉淀 -- 解决、保存、可搜索。

---

### 工作流 4: 知识库定期维护

```
/kb stats                              # 查看整体健康度
/kb orphan                             # 检测孤立笔记
把 "MySQL慢查询" 链接到 "数据库调优"      # vault_update 补充 wikilink
/kb list --status draft                # 审阅草稿，提升为 permanent
```

---

## 4. 笔记类型说明

| type | 用途 | 典型场景 | 存放位置 |
|------|------|----------|----------|
| `permanent` | 永久知识 | 设计模式、最佳实践 | `~/vault/permanent/` |
| `solution` | 解决方案 | 排查过程+根因+步骤 | `~/vault/permanent/` 或 `<project>/` |
| `concept` | 概念解释 | 技术名词、原理、学习笔记 | `~/vault/permanent/` |
| `tool` | 工具技巧 | CLI备忘、IDE配置、踩坑 | `~/vault/permanent/` |
| `session-log` | 会话日志 | 每日工作记录 | `~/vault/logs/` 或 `<project>/logs/` |
| `code-graph` | 代码图谱 | graphify 自动生成 | `~/vault/graphify/<project>/` |

**状态流转:** `draft` -> `review` -> `permanent` (可降级为 `archived`)

**链接规范:** 每篇 permanent 至少 2 个 `[[wikilink]]`。save 时自动扫描已知笔记标题并替换。也可手动添加 `[[笔记名|别名]]`。

---

## 5. 常见问题

### Q: Vault 放哪里？
默认 `~/vault/`（Windows 即 `C:\Users\<用户名>\vault\`）。可通过 MCP 工具参数 `vault_dir` 或环境变量 `VAULT_DIR` 自定义。

### Q: graphify 未安装怎么办？
graphify 是可选依赖，不影响核心功能。未安装时 `/kb graphify` 提示 `pip install graphifyy`。

### Q: 如何在 Obsidian 中查看笔记？
打开 Obsidian -> "Open folder as vault" -> 选择 `~/vault/`。Graph View 自动展示 wikilink 连线。Obsidian 非必需，任何编辑器都可。

### Q: 笔记怎么备份？
```bash
cd ~/vault && git init && git add . && git commit -m "备份"   # Git 版本控制
cp -r ~/vault D:/Backup/vault-$(date +%Y%m%d)                # 定时拷贝
```
或直接用 iCloud/Dropbox/OneDrive 同步。SQLite 索引可通过 `/kb init` 重建。

### Q: 保存后搜不到？
检查 `~/vault/` 下 .md 文件是否存在。若索引异常：`rm ~/vault/.vault.db` 后重新 `/kb init`（不影响已有笔记）。

### Q: 中文搜索效果如何提升？
用关键词组合而非完整句子（如 `"Windows 编码 乱码"` 优于长句）。标题精确匹配不受分词影响。善用 `--tag` 过滤。

### Q: 笔记可以删除吗？
暂不提供 `/kb delete`（防误删）。可手动删除 .md 文件后 `/kb init` 重建索引。

### Q: 多项目能共用一个 Vault 吗？
这是核心设计。所有项目在同一 Vault 不同子目录下，`/kb search` 默认搜索全局，也可 `--project` 过滤。

### Q: MCP Server 启动失败？
```bash
python --version      # 确认 3.10+
pip show mcp          # 确认已安装
# 手动启动 MCP Server（无报错退出即正常）
PYTHONIOENCODING=utf-8 python ~/scripts/vault-mcp-server/server.py
claude mcp list       # 验证注册
```

### Q: 与 Claude Code 内置记忆有什么区别？
互补，不替代：内置记忆存项目偏好/角色（单项目），Vault 存知识/方案/代码结构（跨项目共享、永久保存）。

---

*更多技术细节见 [PRD 文档](./prd-knowledge-base.md)。*
