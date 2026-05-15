"""vault_todo_delete — 删除待办。"""
from mcp.types import TextContent

from db import VaultDB
from tools._shared import check_required, json_reply


TOOL_SCHEMA = {
    "name": "vault_todo_delete",
    "description": "删除待办记录。",
    "inputSchema": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "待办 ID"}},
        "required": ["id"],
    },
}


async def handle_todo_delete(arguments: dict) -> list[TextContent]:
    ok, err = check_required(arguments, "id")
    if not ok:
        return err
    todo_id = arguments["id"]

    with VaultDB() as db:
        success = db.delete_todo(todo_id)

    return json_reply({"status": "ok" if success else "error", "id": todo_id, "action": "deleted"})
