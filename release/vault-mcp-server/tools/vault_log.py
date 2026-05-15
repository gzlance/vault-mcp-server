"""vault_log — 写入会话日志。"""
import json
from datetime import date, datetime

from mcp.types import TextContent
from db import VaultDB
from tools._shared import check_required, get_vault_dir, json_reply

TOOL_SCHEMA = {
    "name": "vault_log",
    "description": "写入会话日志到 Vault。记录做了什么、决策、待办事项。v2.0 同步 todos 到独立待办表。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "project": {"type": "string", "description": "项目名"},
            "summary": {"type": "string", "description": "做了什么"},
            "decisions": {"type": "array", "items": {"type": "string"}, "description": "决策列表"},
            "todos": {"type": "array", "items": {"type": "string"}, "description": "待办列表"},
        },
        "required": ["project", "summary"],
    },
}


async def handle_log(args: dict) -> list[TextContent]:
    ok, err = check_required(args, "project", "summary")
    if not ok:
        return err

    project = args["project"]
    summary = args["summary"]
    decisions = args.get("decisions", [])
    todos = args.get("todos", [])
    vault_dir = get_vault_dir(args)

    today = date.today().isoformat()
    filename = f"{today}-session-{datetime.now().strftime('%H%M%S')}.md"
    log_dir = vault_dir / project / "logs" if project else vault_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_path = log_dir / filename
    rel_path = str(file_path.relative_to(vault_dir)).replace("\\", "/")

    md = f"""---
title: "会话日志 — {today}"
tags: [session-log]
created: {today}
updated: {today}
type: session-log
project: {project or "uncategorized"}
---

# 会话日志 — {today}

## 做了什么

{summary}

"""
    if decisions:
        md += "## 决策\n\n"
        for d in decisions:
            md += f"- {d}\n"
        md += "\n"
    if todos:
        md += "## 待办\n\n"
        for t in todos:
            md += f"- [ ] {t}\n"
        md += "\n"

    file_path.write_text(md, encoding="utf-8")

    synced = 0
    with VaultDB() as db:
        log_id = db.insert_session_log(
            project=project or "uncategorized", date=today, file_path=rel_path,
            summary=summary, decisions=json.dumps(decisions, ensure_ascii=False),
            todos=json.dumps(todos, ensure_ascii=False),
        )
        for todo in todos:
            if todo and todo.strip():
                tid = db.upsert_todo(project or "uncategorized", todo.strip(), source_log_id=log_id)
                if tid > 0:
                    synced += 1

    return json_reply({"status": "ok", "file_path": rel_path, "todos_synced": synced})
