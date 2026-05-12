"""Vault MCP Server — 工具模块共享函数。"""

import json
from pathlib import Path

from mcp.types import TextContent

DEFAULT_VAULT_DIR = Path.home() / "vault"


def json_reply(data: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]


def get_vault_dir(args: dict) -> Path:
    vault_dir = args.get("vault_dir")
    return Path(vault_dir).expanduser().resolve() if vault_dir else DEFAULT_VAULT_DIR


def check_required(args: dict, *fields: str) -> tuple[bool, list[TextContent] | None]:
    """检查必填字段，缺失时返回 (False, error_json)。"""
    for field in fields:
        value = args.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return False, json_reply({"status": "error", "message": f"缺少必填参数: {field}"})
    return True, None


def check_tags(tags) -> list[TextContent] | None:
    """每个标签 ≤ 50 字符，失败时返回 error_json。"""
    if not isinstance(tags, list):
        return json_reply({"status": "error", "message": "tags 必须是列表类型"})
    for tag in tags:
        if not isinstance(tag, str):
            return json_reply({"status": "error", "message": f"标签值必须为字符串: {tag}"})
        if len(tag) > 50:
            return json_reply(
                {"status": "error", "message": f"标签过长（最大50字符）: {tag[:50]}..."}
            )
    return None


def check_title(title: str) -> list[TextContent] | None:
    """标题非空且 ≤ 200 字符，失败时返回 error_json。"""
    if not title or not title.strip():
        return json_reply({"status": "error", "message": "标题不能为空"})
    if len(title) > 200:
        return json_reply(
            {"status": "error", "message": f"标题过长（最长200字符，当前{len(title)}字符）"}
        )
    return None
