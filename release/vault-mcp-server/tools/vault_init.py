"""vault_init — 初始化 Vault 目录结构和 SQLite 索引。"""
from datetime import date
from pathlib import Path

from mcp.types import TextContent
from db import VaultDB
from tools._shared import get_vault_dir, json_reply

TEMPLATE_NOTE = """---
title: "{title}"
tags: []
created: {date}
updated: {date}
type: permanent
---

# {title}

"""
TEMPLATE_SESSION_LOG = """---
title: "{title}"
tags: [session-log]
created: {date}
updated: {date}
type: session-log
project: {project}
---

# 会话日志 — {date}

## 做了什么

## 决策

## 待办

"""

TOOL_SCHEMA = {
    "name": "vault_init",
    "description": "初始化 Vault 目录结构、模板文件和 SQLite 索引库。幂等操作——已初始化的部分自动跳过。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "vault_dir": {"type": "string", "description": "Vault 根目录路径，默认 ~/vault"},
            "project": {"type": "string", "description": "可选，同时初始化项目子目录"},
        },
    },
}


async def handle_init(args: dict) -> list[TextContent]:
    vault_dir = get_vault_dir(args)
    project = args.get("project")
    results = []

    for subdir in ["permanent", "templates", "logs", "graphify"]:
        dir_path = vault_dir / subdir
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            results.append(f"created dir: {dir_path}")

    templates_dir = vault_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    default_tpl = templates_dir / "default-note.md"
    if not default_tpl.exists():
        default_tpl.write_text(
            TEMPLATE_NOTE.format(title="笔记标题", date=date.today().isoformat()), encoding="utf-8"
        )
        results.append("created template: default-note.md")

    session_tpl = templates_dir / "session-log.md"
    if not session_tpl.exists():
        session_tpl.write_text(
            TEMPLATE_SESSION_LOG.format(title="会话日志", date=date.today().isoformat(), project="{project}"),
            encoding="utf-8",
        )
        results.append("created template: session-log.md")

    with VaultDB() as db:
        db.initialize()
    results.append("sqlite schema initialized")

    vault_claude = vault_dir / "CLAUDE.md"
    if not vault_claude.exists():
        vault_claude.write_text(
            """# Vault — Claude Code 知识库

## 笔记规则
- 文件名使用 kebab-case，中文会被自动移除仅保留英文字符
- frontmatter 必填字段：title、tags、created、updated、type
- type 为 permanent 的笔记应至少包含 2 个 [[wikilink]] 引用其他笔记
- 内部链接使用 Obsidian wikilink 格式 `[[note-title]]`

## 三层代码查询策略
修改代码前，按优先级逐层查询：

1. **第一层：graphify_query** — 查找符号归属和调用链（< 10ms）
2. **第二层：vault_search** — 搜索 graphify/ 和 permanent/ 中的模块职责和历史方案（< 50ms）
3. **第三层：直接 Read 源文件** — 仅当前两层信息不足时使用

## 目录结构
- `permanent/` — 永久知识笔记
- `templates/` — 笔记模板
- `logs/` — 全局会话日志
- `<project>/` — 项目笔记（architecture/features/data/logs）
- `graphify/<project>/` — 代码图谱笔记
""",
            encoding="utf-8",
        )
        results.append("created vault CLAUDE.md")

    if project:
        project_dir = vault_dir / project
        for sub in ["architecture", "features", "data", "logs"]:
            (project_dir / sub).mkdir(parents=True, exist_ok=True)
        results.append(f"initialized project: {project}")

    return json_reply({"status": "ok", "actions": results, "vault_dir": str(vault_dir)})
