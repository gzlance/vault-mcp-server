"""vault_list — 结构化列出笔记。"""
from mcp.types import TextContent
from db import VaultDB
from tools._shared import json_reply

TOOL_SCHEMA = {
    "name": "vault_list",
    "description": "按条件结构化列出笔记，支持分页和排序。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
            "project": {"type": "string"},
            "type": {"type": "string"},
            "sort": {"type": "string", "enum": ["created", "updated", "title"]},
            "limit": {"type": "integer", "default": 20},
            "offset": {"type": "integer", "default": 0},
        },
    },
}


async def handle_list(args: dict) -> list[TextContent]:
    db = VaultDB()
    notes = db.list_notes(
        tags=args.get("tags"),
        project=args.get("project"),
        note_type=args.get("type"),
        sort=args.get("sort", "updated"),
        limit=args.get("limit", 20),
        offset=args.get("offset", 0),
    )
    return json_reply({"status": "ok", "count": len(notes), "notes": notes})
