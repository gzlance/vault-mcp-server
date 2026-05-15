"""vault_todo_pending — 恢复待办为待处理。"""
from mcp.types import TextContent

from db import VaultDB
from tools._shared import check_required, json_reply


TOOL_SCHEMA = {
    "name": "vault_todo_pending",
    "description": "恢复待办为待处理状态。",
    "inputSchema": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "待办 ID"}},
        "required": ["id"],
    },
}


async def handle_todo_pending(arguments: dict) -> list[TextContent]:
    ok, err = check_required(arguments, "id")
    if not ok:
        return err
    todo_id = arguments["id"]

    with VaultDB() as db:
        success = db.update_todo_status(todo_id, "pending")

    return json_reply({"status": "ok" if success else "error", "id": todo_id, "action": "pending"})
