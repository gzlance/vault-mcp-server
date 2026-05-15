"""frontmatter 与内容校验（纯函数）。"""

from typing import Any

VALID_TYPES = {"permanent", "solution", "concept", "tool", "session-log", "code-graph"}


def validate_title(title: str) -> str | None:
    """标题非空且 ≤ 200 字符。返回 None 表示通过，返回字符串表示错误。"""
    if not title or not title.strip():
        return "标题不能为空"
    if len(title) > 200:
        return f"标题过长（最长200字符，当前{len(title)}字符）"
    return None


def validate_tags(tags: Any) -> str | None:
    """标签必须是字符串列表，每个 ≤ 50 字符。"""
    if not isinstance(tags, list):
        return "tags 必须是列表类型"
    for tag in tags:
        if not isinstance(tag, str):
            return f"标签值必须为字符串: {tag}"
        if len(tag) > 50:
            return f"标签过长（最大50字符）: {tag[:50]}..."
    return None


def validate_type(note_type: str) -> str | None:
    """类型必须是 6 种合法值之一。"""
    if note_type not in VALID_TYPES:
        return f"无效的笔记类型: {note_type}，合法值: {sorted(VALID_TYPES)}"
    return None


def validate_wikilink_count(note_type: str, count: int) -> str | None:
    """permanent 类型至少 2 个 wikilink。"""
    if note_type == "permanent" and count < 2:
        return f"permanent 类型笔记建议至少包含 2 个 wikilink，当前仅 {count} 个"
    return None
