"""vault_todo_progress — 标记待办进行中。"""
from mcp.types import TextContent

from db import VaultDB
from tools._shared import check_required, json_reply


TOOL_SCHEMA = {
    "name": "vault_todo_progress",
    "description": "标记待办为进行中。",
    "inputSchema": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "待办 ID"}},
        "required": ["id"],
    },
}


async def handle_todo_progress(arguments: dict) -> list[TextContent]:
    ok, err = check_required(arguments, "id")
    if not ok:
        return err
    todo_id = arguments["id"]

    with VaultDB() as db:
        success = db.update_todo_status(todo_id, "in-progress")

    return json_reply({"status": "ok" if success else "error", "id": todo_id, "action": "progress"})
