"""vault_todo_list — 列出项目待办。"""
from mcp.types import TextContent

from db import VaultDB
from tools._shared import get_vault_dir, json_reply


TOOL_SCHEMA = {
    "name": "vault_todo_list",
    "description": "列出项目待办，默认只显示 pending 状态，按创建时间升序。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "project": {"type": "string", "description": "项目名，不传则从 CWD 推断"},
            "status": {
                "type": "string",
                "enum": ["pending", "in-progress", "done"],
            },
        },
    },
}


async def handle_todo_list(arguments: dict) -> list[TextContent]:
    """列出项目待办。"""
    vault_dir = get_vault_dir(arguments)
    from tools._shared import get_project
    project = get_project(arguments, vault_dir)
    status = arguments.get("status")

    with VaultDB() as db:
        todos = db.list_todos(project or "", status=status)

    return json_reply({"status": "ok", "count": len(todos), "todos": todos})
