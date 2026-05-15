"""vault_update — 更新已有笔记的正文内容。"""
from mcp.types import TextContent
from db import VaultDB
from tools._shared import check_required, get_vault_dir, json_reply

TOOL_SCHEMA = {
    "name": "vault_update",
    "description": "更新已有笔记的正文内容，保留原有 frontmatter 并更新 updated 日期。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "note_path": {"type": "string", "description": "笔记文件路径"},
            "new_content": {"type": "string", "description": "替换正文"},
            "append_content": {"type": "string", "description": "追加到正文末尾"},
        },
        "required": ["note_path"],
    },
}


async def handle_update(args: dict) -> list[TextContent]:
    ok, err = check_required(args, "note_path")
    if not ok:
        return err
    if not args.get("new_content") and not args.get("append_content"):
        return json_reply({"status": "error", "message": "需要提供 new_content 或 append_content"})

    note_path = args["note_path"]
    new_content = args.get("new_content")
    append_content = args.get("append_content")
    vault_dir = get_vault_dir(args)

    full_path = vault_dir / note_path
    if not full_path.exists():
        return json_reply({"status": "error", "message": f"文件不存在: {note_path}"})

    if new_content:
        raw = full_path.read_text(encoding="utf-8")
        fm_end = raw.find("---\n", 4)
        updated = (raw[: fm_end + 4] + "\n" + new_content + "\n") if fm_end != -1 else new_content
        full_path.write_text(updated, encoding="utf-8")
        db = VaultDB()
        db.update_note_content(note_path, new_content)
        return json_reply({"status": "ok", "action": "replaced"})

    if append_content:
        with full_path.open("a", encoding="utf-8") as f:
            f.write("\n" + append_content + "\n")
        new_full = full_path.read_text(encoding="utf-8")
        fm_end = new_full.find("---\n", 4)
        body = new_full[fm_end + 4 :] if fm_end != -1 else new_full
        db = VaultDB()
        db.update_note_content(note_path, body)
        return json_reply({"status": "ok", "action": "appended"})

    return json_reply({"status": "error", "message": "需要提供 new_content 或 append_content"})
