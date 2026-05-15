"""vault_search — FTS5 全文搜索。"""
from mcp.types import TextContent
from db import VaultDB
from tools._shared import json_reply

TOOL_SCHEMA = {
    "name": "vault_search",
    "description": "FTS5 全文搜索 Vault 笔记。返回结构化匹配结果，含标题、片段高亮、标签、相关度分数。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "按标签过滤"},
            "project": {"type": "string", "description": "按项目过滤"},
            "type": {"type": "string", "description": "按笔记类型过滤"},
            "limit": {"type": "integer", "default": 10},
            "offset": {"type": "integer", "default": 0},
        },
        "required": ["query"],
    },
}


async def handle_search(args: dict) -> list[TextContent]:
    query = args.get("query", "")
    if not query or not query.strip():
        return json_reply({"status": "ok", "query": query, "count": 0, "results": []})
    query = query.replace('"', '""')  # FTS5 引号转义
    tags = args.get("tags")
    project = args.get("project")
    note_type = args.get("type")
    limit = args.get("limit", 10)
    offset = args.get("offset", 0)

    db = VaultDB()
    tags_str = ",".join(tags) if isinstance(tags, list) else tags
    with db:
        results = db.search(
            query=query, tags=tags_str, project=project, type=note_type, limit=limit, offset=offset,
        )

    return json_reply({"status": "ok", "query": query, "count": len(results), "results": results})
