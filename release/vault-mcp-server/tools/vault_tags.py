"""vault_tags — 标签列表及模糊搜索。"""
from mcp.types import TextContent
from db import VaultDB
from tools._shared import json_reply

TOOL_SCHEMA = {
    "name": "vault_tags",
    "description": "返回所有已用标签及使用频次，支持标签模糊搜索。",
    "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "标签模糊搜索关键词"}},
    },
}


async def handle_tags(args: dict) -> list[TextContent]:
    query = args.get("query")
    db = VaultDB()
    tags = db.get_all_tags(query=query)
    return json_reply({"status": "ok", "count": len(tags), "tags": tags})
