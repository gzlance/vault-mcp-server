"""vault_orphan — 检测孤立笔记。"""
from mcp.types import TextContent
from db import VaultDB
from tools._shared import json_reply

TOOL_SCHEMA = {
    "name": "vault_orphan",
    "description": "检测孤立笔记——没有被任何其他笔记引用(入度为0)或不引用任何笔记(出度为0)的笔记。",
    "inputSchema": {"type": "object", "properties": {}},
}


async def handle_orphan(args: dict) -> list[TextContent]:
    db = VaultDB()
    orphans = db.find_orphans()
    return json_reply({
        "status": "ok",
        "no_incoming_count": len(orphans["no_incoming"]),
        "no_outgoing_count": len(orphans["no_outgoing"]),
        "no_incoming": orphans["no_incoming"],
        "no_outgoing": orphans["no_outgoing"],
    })
