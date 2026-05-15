"""vault_stats — 知识库统计面板。"""
from mcp.types import TextContent
from db import VaultDB
from tools._shared import json_reply

TOOL_SCHEMA = {
    "name": "vault_stats",
    "description": "返回知识库统计面板：笔记总数、按类型/项目分布、Top 标签、最近新增、链接密度。",
    "inputSchema": {"type": "object", "properties": {}},
}


async def handle_stats(args: dict) -> list[TextContent]:
    db = VaultDB()
    stats = db.get_stats()
    return json_reply({"status": "ok", **stats})
