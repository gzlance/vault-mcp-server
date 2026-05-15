"""vault_delete — 按标题定位删除笔记，级联清理。"""
from pathlib import Path

from mcp.types import TextContent

from db import VaultDB
from services.resolver import resolve_title_to_path
from tools._shared import check_required, get_vault_dir, json_reply


TOOL_SCHEMA = {
    "name": "vault_delete",
    "description": "按标题删除笔记，级联清理 .md 文件 + FTS5 索引 + wikilink 引用 + 标签统计。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "笔记标题"},
            "project": {"type": "string", "description": "项目名，不传则从 CWD 推断"},
        },
        "required": ["title"],
    },
}


async def handle_delete(arguments: dict) -> list[TextContent]:
    ok, err = check_required(arguments, "title")
    if not ok:
        return err

    title = arguments["title"]
    vault_dir = get_vault_dir(arguments)
    from tools._shared import get_project
    project = get_project(arguments, vault_dir)

    with VaultDB() as db:
        # 三级解析标题 → 路径
        result = resolve_title_to_path(
            title=title,
            project=project,
            exact_matcher=lambda t, p: _exact_match(db, t, p),
            fts5_matcher=lambda t, p: db.search_by_title_fuzzy(t, p),
        )

        if result is None or not result.file_path:
            return json_reply({
                "status": "error",
                "message": f"未找到匹配笔记: {title}",
                "candidates": result.candidates if result else [],
            })

        # 安全检查：确保路径在 vault_dir 内
        abs_path = (vault_dir / result.file_path).resolve()
        if not str(abs_path).startswith(str(vault_dir.resolve())):
            return json_reply({"status": "error", "message": "路径遍历拒绝"})

        # 级联删除
        deleted = db.delete_note(result.file_path)
        if deleted:
            # 删除物理文件
            if abs_path.exists():
                abs_path.unlink()
            return json_reply({
                "status": "ok",
                "deleted": {
                    "title": deleted["title"],
                    "file_path": result.file_path,
                    "matched_by": result.matched_by,
                },
            })
        else:
            return json_reply({"status": "error", "message": f"删除失败: {title}"})


def _exact_match(db, title: str, project: str | None) -> list[dict]:
    """精确匹配包装器：返回 list 格式供 resolver 使用。"""
    if project:
        note = db.get_note_by_title_project(title, project)
    else:
        note = db.get_note_by_title(title)
    return [note] if note else []
