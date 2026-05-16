"""vault_save — 保存知识笔记到 Vault。"""
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

from mcp.types import TextContent
from db import VaultDB
from services import wikilink as wikilink_svc
from tools._shared import (
    check_required, check_tags, check_title, get_project, get_vault_dir, json_reply,
)

# 笔记类型到项目子目录的映射
_TYPE_TO_SUBDIR: dict[str, str] = {
    "permanent": "architecture",
    "concept": "architecture",
    "solution": "features",
    "tool": "data",
}


def _type_to_subdir(note_type: str) -> str:
    return _TYPE_TO_SUBDIR.get(note_type, "")


def _resolve_file_path(
    vault_dir: Path, title: str, note_type: str, project: str | None = None
) -> Path:
    """根据类型和项目决定文件保存路径。"""
    filename = wikilink_svc.to_kebab(title) + ".md"
    if note_type == "session-log":
        today = date.today().isoformat()
        if project:
            return vault_dir / project / "logs" / f"{today}-{filename}"
        else:
            return vault_dir / "logs" / f"{today}-{filename}"
    elif note_type == "code-graph":
        return vault_dir / "graphify" / (project or "") / filename
    elif project:
        subdir = _type_to_subdir(note_type)
        return vault_dir / project / subdir / filename
    else:
        return vault_dir / "permanent" / filename


def _build_frontmatter(
    title: str, tags: list[str], note_type: str, project: str | None
) -> str:
    """生成 YAML frontmatter 文本（v2.0 移除 status 字段）。"""
    today = date.today().isoformat()
    lines = [
        "---",
        f'title: "{title}"',
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        f"created: {today}",
        f"updated: {today}",
        f"type: {note_type}",
    ]
    if project:
        lines.append(f"project: {project}")
    lines.append("---\n")
    return "\n".join(lines)


TOOL_SCHEMA = {
    "name": "vault_save",
    "description": "保存知识笔记到 Vault。校验 frontmatter 必填字段、匹配已有笔记生成 wikilink、写入 .md 文件并更新 SQLite 索引。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "笔记标题"},
            "content": {"type": "string", "description": "Markdown 正文(不含 frontmatter)"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
            "type": {
                "type": "string",
                "enum": ["permanent", "solution", "concept", "tool", "session-log", "code-graph"],
                "description": "笔记类型",
            },
            "project": {"type": "string", "description": "归属项目名"},
            "vault_dir": {"type": "string", "description": "Vault 根目录路径，默认 ~/vault"},
        },
        "required": ["title", "content", "tags", "type"],
    },
}


async def handle_save(args: dict) -> list[TextContent]:
    ok, err = check_required(args, "title", "content", "tags", "type")
    if not ok:
        return err
    err = check_title(args["title"]) or check_tags(args["tags"])
    if err:
        return err

    title = args["title"]
    content = args["content"]
    tags = args["tags"]
    note_type = args["type"]
    vault_dir = get_vault_dir(args)
    project = get_project(args, vault_dir)

    # kb-save 未传 project 且 CWD 无匹配项目目录时，提示初始化
    if "project" not in args and project is None:
        return json_reply({
            "status": "error",
            "message": "未找到当前项目目录，请先 /kb-init 初始化知识库",
        })

    file_path = _resolve_file_path(vault_dir, title, note_type, project)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    rel_path = str(file_path.relative_to(vault_dir)).replace("\\", "/")
    is_update = file_path.exists()

    with VaultDB() as db:
        if not is_update:
            old_note = db.get_note_by_title(title)
            if old_note:
                old_path = vault_dir / old_note["file_path"]
                if old_path.exists():
                    file_path = old_path
                    rel_path = old_note["file_path"]
                    is_update = True

        if is_update:
            existing = db.get_note_by_path(rel_path)
            if existing and existing.get("title") != title:
                base = file_path.stem
                suffix = 2
                while file_path.exists():
                    file_path = file_path.parent / f"{base}-{suffix}.md"
                    suffix += 1
                file_path.parent.mkdir(parents=True, exist_ok=True)
                rel_path = str(file_path.relative_to(vault_dir)).replace("\\", "/")
                is_update = False

        all_titles = db.get_all_titles()
        other_titles = [t for t in all_titles if t != title]
        auto_linked_content, auto_link_count = wikilink_svc.auto_link_titles(content, other_titles)
        if auto_link_count > 0:
            content = auto_linked_content

        frontmatter = _build_frontmatter(title, tags, note_type, project)
        full_md = frontmatter + "\n" + content + "\n"

        usage = shutil.disk_usage(file_path.parent)
        free_mb = usage.free // (1024 * 1024)
        if usage.free < 10 * 1024 * 1024:
            return json_reply({
                "status": "error",
                "message": f"磁盘空间不足（仅剩 {free_mb}MB），无法保存笔记",
            })

        file_path.write_text(full_md, encoding="utf-8")
        wikilink_targets = wikilink_svc.extract_wikilinks(content)

        today = date.today().isoformat()
        tags_json = json.dumps(tags, ensure_ascii=False)
        word_count = len(content.split())
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if is_update and db.update_note_content(rel_path, content):
            pass
        else:
            note_id = db.insert_note(
                title=title, file_path=rel_path, tags=tags_json, type=note_type,
                project=project or "", created=today, updated=today,
                word_count=word_count, checksum=checksum,
            )
            db.reindex_note(note_id, title, content)

        db.update_tags(tags)
        if wikilink_targets:
            db.update_wikilinks(rel_path, [t["target"] for t in wikilink_targets])

    warnings_list = []
    if note_type == "permanent" and len(wikilink_targets) < 2:
        warnings_list.append(
            f"permanent 类型笔记建议至少包含 2 个 wikilink，当前仅 {len(wikilink_targets)} 个，"
            f"请考虑添加相关笔记链接"
        )

    response = {
        "status": "ok",
        "action": "updated" if is_update else "created",
        "file_path": rel_path,
        "wikilinks_found": len(wikilink_targets),
        "wikilinks_auto_suggested": auto_link_count,
    }
    if warnings_list:
        response["warnings"] = warnings_list

    return json_reply(response)
