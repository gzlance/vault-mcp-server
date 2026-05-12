"""Vault MCP Server — 核心知识库工具实现。

提供 vault_init/save/search/resume/list/stats/orphan/update/tags/log 的处理逻辑。
"""

import hashlib
import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from mcp.types import TextContent

from db import VaultDB
from tools._shared import (
    check_required,
    check_tags,
    check_title,
    get_vault_dir,
    json_reply,
)

# ── 目录结构模板 ──
VAULT_DIRS = [
    "permanent",
    "templates",
    "logs",
    "graphify",
]

TEMPLATE_NOTE = """---
title: "{title}"
tags: []
created: {date}
updated: {date}
status: draft
type: permanent
---

# {title}

"""
TEMPLATE_SESSION_LOG = """---
title: "{title}"
tags: [session-log]
created: {date}
updated: {date}
status: draft
type: session-log
project: {project}
---

# 会话日志 — {date}

## 做了什么

## 决策

## 待办

"""

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[^\]\]]*)?\]\]")


# ── 输入校验工具（已移至 tools._shared）──


def _to_kebab(title: str) -> str:
    """将标题转为 kebab-case 文件名（不含扩展名）。"""
    name = title.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    return name.strip("-")


# 笔记类型到项目子目录的映射
_TYPE_TO_SUBDIR: dict[str, str] = {
    "permanent": "architecture",
    "concept": "architecture",
    "solution": "features",
    "tool": "data",
}


def _type_to_subdir(note_type: str) -> str:
    """返回笔记类型对应的项目子目录，未知类型默认放根目录。"""
    return _TYPE_TO_SUBDIR.get(note_type, "")


def _resolve_file_path(
    vault_dir: Path, title: str, note_type: str, project: str | None = None
) -> Path:
    """根据类型和项目决定文件保存路径。"""
    filename = _to_kebab(title) + ".md"
    if note_type == "session-log":
        today = date.today().isoformat()
        if project:
            return vault_dir / project / "logs" / f"{today}-{filename}"
        else:
            return vault_dir / "logs" / f"{today}-{filename}"
    elif note_type == "code-graph":
        return vault_dir / "graphify" / (project or "") / filename
    elif project:
        # 按笔记类型路由到项目子目录
        subdir = _type_to_subdir(note_type)
        return vault_dir / project / subdir / filename
    else:
        return vault_dir / "permanent" / filename


def _extract_wikilinks(content: str) -> list[dict]:
    """从 Markdown 正文中提取 [[wikilink]] 目标。"""
    targets = []
    for match in WIKILINK_RE.finditer(content):
        target_title = match.group(1).strip()
        start = max(0, match.start() - 30)
        end = min(len(content), match.end() + 30)
        context = content[start:end].replace("\n", " ")
        targets.append({"target": _to_kebab(target_title) + ".md", "context": context})
    return targets


def _find_wikilinkable_spans(content: str, known_titles: list[str]) -> list[dict]:
    """检测正文中哪些已知标题以纯文本形式出现（未被 [[]] 包裹）。

    返回列表，每个元素为 {"start": int, "end": int, "title": str}，
    按 start 降序排列，方便从后往前替换避免偏移问题。
    """
    # 收集所有已存在的 wikilink 区间，避免在这些区间内重复匹配
    existing_ranges = []
    for match in WIKILINK_RE.finditer(content):
        existing_ranges.append((match.start(), match.end()))

    def _inside_existing(pos: int) -> bool:
        return any(s <= pos < e for s, e in existing_ranges)

    spans = []
    for title in known_titles:
        if not title or not title.strip():
            continue
        title_clean = title.strip()
        # 在正文中查找所有出现的纯文本标题（大小写不敏感）
        pattern = re.compile(re.escape(title_clean), re.IGNORECASE)
        for match in pattern.finditer(content):
            # 跳过已位于 [[...]] 内部的匹配
            if _inside_existing(match.start()):
                continue
            # 跳过位于 YAML frontmatter 内的匹配
            if match.start() < 4:
                continue
            spans.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "title": title_clean,
                }
            )

    # 去重：按 start 排序，重叠区间保留更长的
    spans.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))
    merged = []
    for span in spans:
        if merged and span["start"] < merged[-1]["end"]:
            # 重叠区间，保留更长的
            if (span["end"] - span["start"]) > (merged[-1]["end"] - merged[-1]["start"]):
                merged[-1] = span
        else:
            merged.append(span)

    # 按 start 降序排列便于从后往前替换
    merged.sort(key=lambda s: s["start"], reverse=True)
    return merged


def _suggest_wikilinks(content: str, known_titles: list[str]) -> list[dict]:
    """检测可自动建立 wikilink 的纯文本标题，返回建议列表。

    返回 [{"target": str, "context": str}, ...]。
    """
    spans = _find_wikilinkable_spans(content, known_titles)
    suggestions = []
    for span in spans:
        start_ctx = max(0, span["start"] - 30)
        end_ctx = min(len(content), span["end"] + 30)
        context = content[start_ctx:end_ctx].replace("\n", " ")
        suggestions.append(
            {
                "target": _to_kebab(span["title"]) + ".md",
                "context": context,
            }
        )
    return suggestions


def _auto_link_titles(content: str, known_titles: list[str]) -> tuple[str, int]:
    """将正文中的纯文本标题替换为 [[title]] wikilink 格式。

    返回 (new_content, count)。
    """
    spans = _find_wikilinkable_spans(content, known_titles)
    new_content = content
    for span in spans:
        new_content = (
            new_content[: span["start"]] + f"[[{span['title']}]]" + new_content[span["end"] :]
        )
    return new_content, len(spans)


def _build_frontmatter(
    title: str, tags: list[str], note_type: str, project: str | None, status: str
) -> str:
    """生成 YAML frontmatter 文本。"""
    today = date.today().isoformat()
    lines = [
        "---",
        f'title: "{title}"',
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        f"created: {today}",
        f"updated: {today}",
        f"status: {status}",
        f"type: {note_type}",
    ]
    if project:
        lines.append(f"project: {project}")
    lines.append("---\n")
    return "\n".join(lines)


# ── vault_init ──


async def handle_init(args: dict) -> list[TextContent]:
    vault_dir = get_vault_dir(args)
    project = args.get("project")
    results = []

    # 1. 创建目录结构
    for subdir in VAULT_DIRS:
        dir_path = vault_dir / subdir
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            results.append(f"created dir: {dir_path}")

    # 2. 创建模板文件
    templates_dir = vault_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    default_tpl = templates_dir / "default-note.md"
    if not default_tpl.exists():
        default_tpl.write_text(
            TEMPLATE_NOTE.format(title="笔记标题", date=date.today().isoformat()), encoding="utf-8"
        )
        results.append("created template: default-note.md")

    session_tpl = templates_dir / "session-log.md"
    if not session_tpl.exists():
        session_tpl.write_text(
            TEMPLATE_SESSION_LOG.format(
                title="会话日志", date=date.today().isoformat(), project="{project}"
            ),
            encoding="utf-8",
        )
        results.append("created template: session-log.md")

    # 3. 初始化 SQLite 表结构
    with VaultDB() as db:
        db.initialize()
    results.append("sqlite schema initialized")

    # 3.5 创建 Vault CLAUDE.md（幂等——已存在则跳过）
    vault_claude = vault_dir / "CLAUDE.md"
    if not vault_claude.exists():
        vault_claude.write_text(
            """# Vault — Claude Code 知识库

## 笔记规则
- 文件名使用 kebab-case，中文会被自动移除仅保留英文字符
- frontmatter 必填字段：title、tags、created、updated、status、type
- type 为 permanent 的笔记应至少包含 2 个 [[wikilink]] 引用其他笔记
- 内部链接使用 Obsidian wikilink 格式 `[[note-title]]`

## 三层代码查询策略
修改代码前，按优先级逐层查询：

1. **第一层：graphify_query** — 查找符号归属和调用链（< 10ms）
2. **第二层：vault_search** — 搜索 graphify/ 和 permanent/ 中的模块职责和历史方案（< 50ms）
3. **第三层：直接 Read 源文件** — 仅当前两层信息不足时使用

## 目录结构
- `permanent/` — 永久知识笔记
- `templates/` — 笔记模板
- `logs/` — 全局会话日志
- `<project>/` — 项目笔记（architecture/features/data/logs）
- `graphify/<project>/` — 代码图谱笔记
""",
            encoding="utf-8",
        )
        results.append("created vault CLAUDE.md")

    # 4. 如果指定了项目，创建项目子目录
    if project:
        project_dir = vault_dir / project
        for sub in ["architecture", "features", "data", "logs"]:
            (project_dir / sub).mkdir(parents=True, exist_ok=True)
        results.append(f"initialized project: {project}")

    return json_reply({"status": "ok", "actions": results, "vault_dir": str(vault_dir)})


# ── vault_save ──


async def handle_save(args: dict) -> list[TextContent]:
    # 输入校验
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
    project = args.get("project")
    status = args.get("status", "draft")
    vault_dir = get_vault_dir(args)

    # 1. 确定文件路径，确保目录存在
    file_path = _resolve_file_path(vault_dir, title, note_type, project)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    rel_path = str(file_path.relative_to(vault_dir)).replace("\\", "/")
    is_update = file_path.exists()

    with VaultDB() as db:
        # 1.5 文件名冲突检测：如果同名文件已存在但属于不同笔记，追加数字后缀
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

        # 1.6 自动 wikilink：检测正文中出现的已知笔记标题，替换为 [[title]] 格式
        all_titles = db.get_all_titles()
        other_titles = [t for t in all_titles if t != title]
        auto_linked_content, auto_link_count = _auto_link_titles(content, other_titles)
        if auto_link_count > 0:
            content = auto_linked_content

        # 2. 构建完整 Markdown（frontmatter + 正文）
        frontmatter = _build_frontmatter(title, tags, note_type, project, status)
        full_md = frontmatter + "\n" + content + "\n"

        # 3. 检查磁盘空间（要求至少剩余 10MB）
        usage = shutil.disk_usage(file_path.parent)
        free_mb = usage.free // (1024 * 1024)
        if usage.free < 10 * 1024 * 1024:
            return json_reply(
                {
                    "status": "error",
                    "message": f"磁盘空间不足（仅剩 {free_mb}MB），无法保存笔记",
                }
            )

        # 4. 写入文件
        file_path.write_text(full_md, encoding="utf-8")

        # 5. 提取 wikilink 目标
        wikilink_targets = _extract_wikilinks(content)

        # 6. 更新数据库索引
        today = date.today().isoformat()
        tags_json = json.dumps(tags, ensure_ascii=False)
        word_count = len(content.split())
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if is_update and db.update_note_content(rel_path, content):
            pass  # 更新成功
        else:
            note_id = db.insert_note(
                title=title,
                file_path=rel_path,
                tags=tags_json,
                type=note_type,
                project=project or "",
                status=status,
                created=today,
                updated=today,
                word_count=word_count,
                checksum=checksum,
            )
            db.reindex_note(note_id, title, content)

        # 7. 更新标签统计
        db.update_tags(tags)

        # 8. 更新 wikilink 引用图
        if wikilink_targets:
            db.update_wikilinks(rel_path, [t["target"] for t in wikilink_targets])

    # 构建 warning 列表
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


# ── vault_search ──


async def handle_search(args: dict) -> list[TextContent]:
    query = args.get("query", "")
    if not query or not query.strip():
        return json_reply({"status": "ok", "query": query, "count": 0, "results": []})
    # 转义 FTS5 双引号：FTS5 中使用 "" 表示一个字面双引号
    query = query.replace('"', '""')
    tags = args.get("tags")
    project = args.get("project")
    note_type = args.get("type")
    limit = args.get("limit", 10)
    offset = args.get("offset", 0)

    db = VaultDB()
    tags_str = ",".join(tags) if isinstance(tags, list) else tags
    with db:
        results = db.search(
            query=query,
            tags=tags_str,
            project=project,
            type=note_type,
            limit=limit,
            offset=offset,
        )

    return json_reply({"status": "ok", "query": query, "count": len(results), "results": results})


# ── vault_resume ──


async def handle_resume(args: dict) -> list[TextContent]:
    # 输入校验
    ok, err = check_required(args, "project")
    if not ok:
        return err

    project = args["project"]
    log_count = args.get("log_count", 3)
    vault_dir = get_vault_dir(args)

    db = VaultDB()
    logs = db.get_recent_logs(project, count=log_count)
    arch_notes = db.get_recent_architecture_notes(project, limit=5)

    # 读取会话日志的完整内容
    enriched_logs = []
    for log in logs:
        log_path = vault_dir / log["file_path"]
        if log_path.exists():
            log["content_preview"] = log_path.read_text(encoding="utf-8")[:2000]
        else:
            log["content_preview"] = "(文件不存在)"
        enriched_logs.append(log)

    return json_reply(
        {
            "status": "ok",
            "project": project,
            "recent_logs": enriched_logs,
            "recent_architecture_notes": arch_notes,
        }
    )


# ── vault_list ──


async def handle_list(args: dict) -> list[TextContent]:
    db = VaultDB()
    notes = db.list_notes(
        tags=args.get("tags"),
        project=args.get("project"),
        note_type=args.get("type"),
        status=args.get("status"),
        sort=args.get("sort", "updated"),
        limit=args.get("limit", 20),
        offset=args.get("offset", 0),
    )
    return json_reply({"status": "ok", "count": len(notes), "notes": notes})


# ── vault_stats ──


async def handle_stats(args: dict) -> list[TextContent]:
    db = VaultDB()
    stats = db.get_stats()
    return json_reply({"status": "ok", **stats})


# ── vault_orphan ──


async def handle_orphan(args: dict) -> list[TextContent]:
    db = VaultDB()
    orphans = db.find_orphans()
    return json_reply(
        {
            "status": "ok",
            "no_incoming_count": len(orphans["no_incoming"]),
            "no_outgoing_count": len(orphans["no_outgoing"]),
            "no_incoming": orphans["no_incoming"],
            "no_outgoing": orphans["no_outgoing"],
        }
    )


# ── vault_update ──


async def handle_update(args: dict) -> list[TextContent]:
    # 输入校验
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
        # 保留原有 frontmatter，替换正文
        raw = full_path.read_text(encoding="utf-8")
        fm_end = raw.find("---\n", 4)
        if fm_end != -1:
            updated = raw[: fm_end + 4] + "\n" + new_content + "\n"
        else:
            updated = new_content
        full_path.write_text(updated, encoding="utf-8")
        db = VaultDB()
        db.update_note_content(note_path, new_content)
        return json_reply({"status": "ok", "action": "replaced"})

    elif append_content:
        with full_path.open("a", encoding="utf-8") as f:
            f.write("\n" + append_content + "\n")
        # 重新计算索引
        new_full = full_path.read_text(encoding="utf-8")
        fm_end = new_full.find("---\n", 4)
        body = new_full[fm_end + 4 :] if fm_end != -1 else new_full
        db = VaultDB()
        db.update_note_content(note_path, body)
        return json_reply({"status": "ok", "action": "appended"})

    return json_reply({"status": "error", "message": "需要提供 new_content 或 append_content"})


# ── vault_tags ──


async def handle_tags(args: dict) -> list[TextContent]:
    query = args.get("query")
    db = VaultDB()
    tags = db.get_all_tags(query=query)
    return json_reply({"status": "ok", "count": len(tags), "tags": tags})


# ── vault_log ──


async def handle_log(args: dict) -> list[TextContent]:
    # 输入校验
    ok, err = check_required(args, "project", "summary")
    if not ok:
        return err

    project = args["project"]
    summary = args["summary"]
    decisions = args.get("decisions", [])
    todos = args.get("todos", [])
    vault_dir = get_vault_dir(args)

    today = date.today().isoformat()
    filename = f"{today}-session-{datetime.now().strftime('%H%M%S')}.md"
    log_dir = vault_dir / project / "logs" if project else vault_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_path = log_dir / filename
    rel_path = str(file_path.relative_to(vault_dir)).replace("\\", "/")

    # 构建 Markdown 内容
    md = f"""---
title: "会话日志 — {today}"
tags: [session-log]
created: {today}
updated: {today}
status: draft
type: session-log
project: {project or "uncategorized"}
---

# 会话日志 — {today}

## 做了什么

{summary}

"""
    if decisions:
        md += "## 决策\n\n"
        for d in decisions:
            md += f"- {d}\n"
        md += "\n"

    if todos:
        md += "## 待办\n\n"
        for t in todos:
            md += f"- [ ] {t}\n"
        md += "\n"

    file_path.write_text(md, encoding="utf-8")

    # 写入数据库
    with VaultDB() as db:
        db.insert_session_log(
            project=project or "uncategorized",
            date=today,
            file_path=rel_path,
            summary=summary,
            decisions=json.dumps(decisions, ensure_ascii=False),
            todos=json.dumps(todos, ensure_ascii=False),
        )

    return json_reply({"status": "ok", "file_path": rel_path})
