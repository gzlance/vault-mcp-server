# Vault MCP Server — 发布包

## 文件说明

```
release/
├── vault-mcp-server/       # 源码
│   ├── server.py           # MCP 服务入口（21 工具注册）
│   ├── db.py               # 向后兼容重导出
│   ├── db/                 # 数据库层（6 子模块）
│   ├── services/           # 业务逻辑层（4 模块）
│   ├── tools/              # MCP 工具实现（21 文件）
│   ├── skills/             # 21 个 /kb-xxx Skill 文件
│   ├── tests/              # 测试套件（259 个测试，89% 覆盖）
│   ├── pyproject.toml      # 工具配置
│   └── requirements.txt    # Python 依赖
├── install.sh              # Linux/macOS 安装
└── install.ps1             # Windows 安装
```

## Windows 安装

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
# 可选: -InstallDir "D:\my-vault" -SkipTests
```

## Linux/macOS 安装

```bash
bash install.sh
# 可选: --install-dir /opt/vault-mcp --skip-tests
```

## 安装完成后

1. 完全退出并重启 Claude Code
2. `/kb-init` 初始化
3. `/kb-stats` 验证

## 新版功能（v2.0）

- 独立待办系统（5 个 `/kb-todo-*` 命令，跨会话追踪）
- 笔记删除（`/kb-delete`，标题定位 + 级联清理）
- 学习记录（`/kb-learn`，存入 permanent/）
- 21 个扁平命令（`/kb-<领域>-<动作>`，输入 `/kb` 查看全部）
- CWD 自动推断项目（无需手动传 project）
- 标题定位（delete/update 支持标题而非路径）
- 数据库层拆分（6 子模块）
- 服务层抽取（纯函数，易测试）

## 版本

v2.0 — 2026-05-15
