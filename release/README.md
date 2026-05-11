# Vault MCP Server — 发布包

## 文件说明

```
release/
├── vault-mcp-server/       # 源码
│   ├── server.py           # MCP 服务入口
│   ├── db.py               # SQLite 数据库层
│   ├── requirements.txt    # Python 依赖
│   ├── README.md           # 使用手册
│   ├── INSTALL.md          # 详细安装指南
│   ├── tools/              # MCP 工具实现
│   └── tests/              # 测试套件 (211 个测试)
├── install.sh              # Linux/macOS 全自动安装
└── install.ps1             # Windows 全自动安装
```

## Windows 安装

```powershell
# 解压后进入 release 目录
powershell -ExecutionPolicy Bypass -File install.ps1

# 可选参数
powershell -ExecutionPolicy Bypass -File install.ps1 -InstallDir "D:\my-vault" -SkipTests
```

## Linux/macOS 安装

```bash
# 解压后进入 release 目录
bash install.sh

# 可选参数
bash install.sh --install-dir /opt/vault-mcp --skip-tests
```

## 安装完成后

1. 完全退出并重启 Claude Code
2. 输入「初始化知识库」
3. 输入 `/kb stats` 验证

## 版本

v1.27.1 — 2026-05-10
