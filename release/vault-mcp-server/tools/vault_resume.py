"""vault_resume — 恢复项目工作上下文。"""
from mcp.types import TextContent
from db import VaultDB
from tools._shared import get_project, get_vault_dir, json_reply

TOOL_SCHEMA = {
    "name": "vault_resume",
    "description": "读取项目的最近会话日志、架构决策笔记和未完成待办，用于恢复工作上下文。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "project": {"type": "string", "description": "项目名，不传则从 CWD 推断"},
            "log_count": {"type": "integer", "default": 3, "description": "返回最近 N 个会话日志"},
        },
    },
}


async def handle_resume(args: dict) -> list[TextContent]:
    vault_dir = get_vault_dir(args)
    project = get_project(args, vault_dir)
    log_count = args.get("log_count", 3)

    db = VaultDB()
    logs = db.get_recent_logs(project or "", count=log_count) if project else []
    arch_notes = db.get_recent_architecture_notes(project or "", limit=5) if project else []
    open_todos = db.list_todos(project or "", status="pending") if project else []

    enriched_logs = []
    for log in logs:
        log_path = vault_dir / log["file_path"]
        if log_path.exists():
            log["content_preview"] = log_path.read_text(encoding="utf-8")[:2000]
        else:
            log["content_preview"] = "(文件不存在)"
        enriched_logs.append(log)

    return json_reply({
        "status": "ok",
        "project": project,
        "recent_logs": enriched_logs,
        "recent_architecture_notes": arch_notes,
        "open_todos": open_todos,
    })
