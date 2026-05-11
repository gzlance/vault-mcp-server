"""Vault MCP Server SQLite 数据库层。

提供 Obsidian Vault 知识库的持久化存储，包括：
- 笔记元数据索引（notes 表）
- FTS5 全文搜索（notes_fts 虚拟表）
- 标签使用统计（tag_index 表）
- Wikilink 引用关系图（wikilinks 表）
- Graphify 代码图谱构建记录（graphify_builds 表）
- 会话日志（session_logs 表）

使用 Python 标准库 sqlite3，不引入 ORM。
所有路径操作使用 pathlib.Path，Windows 兼容。
"""

import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path


class VaultDB:
    """Vault 知识库数据库封装。

    所有写操作默认开启 WAL 模式以提升并发性能。
    支持上下文管理器：with VaultDB(path) as db:
    """

    def __init__(self, db_path: str | Path | None = None):
        """初始化数据库连接。

        Args:
            db_path: SQLite 数据库文件路径，默认 ~/.vault-mcp/vault.db
        """
        if db_path is None:
            db_path = Path.home() / ".vault-mcp" / "vault.db"
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection | None = None

    # ── 上下文管理器 ──

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()
        self.conn = None
        return False  # 不吞异常

    def close(self):
        """手动关闭数据库连接。"""
        if self.conn:
            self.conn.commit()
            self.conn.close()
            self.conn = None

    def _connect(self):
        """建立数据库连接，创建目录，启用优化 PRAGMA。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA cache_size=-8000")       # 8MB 页面缓存（负值单位 KB）
        self.conn.execute("PRAGMA mmap_size=268435456")    # 256MB 内存映射 I/O
        self.conn.execute("PRAGMA synchronous=NORMAL")     # 写性能优化（非 FULL 安全模式）
        self.conn.row_factory = sqlite3.Row

    def _ensure_connected(self):
        """懒连接：若尚未连接则自动建立连接。"""
        if self.conn is None:
            self._connect()

    # ── 表结构初始化 ──

    def initialize(self):
        """执行 CREATE TABLE IF NOT EXISTS，幂等操作——已存在的表自动跳过。"""
        self._ensure_connected()
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                file_path   TEXT NOT NULL UNIQUE,
                tags        TEXT,
                type        TEXT NOT NULL DEFAULT 'permanent',
                project     TEXT,
                status      TEXT DEFAULT 'draft',
                created     TEXT NOT NULL,
                updated     TEXT NOT NULL,
                word_count  INTEGER DEFAULT 0,
                checksum    TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                title,
                content,
                tokenize='trigram'  -- trigram 分词器对中英文混合内容均有效
            );

            CREATE TABLE IF NOT EXISTS tag_index (
                tag         TEXT PRIMARY KEY,
                count       INTEGER DEFAULT 0,
                last_used   TEXT
            );

            CREATE TABLE IF NOT EXISTS wikilinks (
                source_path TEXT NOT NULL,
                target_path TEXT NOT NULL,
                context     TEXT,
                PRIMARY KEY (source_path, target_path)
            );

            CREATE TABLE IF NOT EXISTS graphify_builds (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project         TEXT NOT NULL,
                commit_sha      TEXT,
                node_count      INTEGER,
                edge_count      INTEGER,
                community_count INTEGER,
                built_at        TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS session_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project     TEXT,
                date        TEXT NOT NULL,
                file_path   TEXT NOT NULL UNIQUE,
                summary     TEXT,
                decisions   TEXT,
                todos       TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type);
            CREATE INDEX IF NOT EXISTS idx_notes_project ON notes(project);
            CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
            CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated);
            CREATE INDEX IF NOT EXISTS idx_wikilinks_source ON wikilinks(source_path);
            CREATE INDEX IF NOT EXISTS idx_wikilinks_target ON wikilinks(target_path);
            CREATE INDEX IF NOT EXISTS idx_session_logs_project ON session_logs(project);
            CREATE INDEX IF NOT EXISTS idx_session_logs_date ON session_logs(date);
            CREATE INDEX IF NOT EXISTS idx_graphify_builds_project_built_at ON graphify_builds(project, built_at);
            CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title);
            CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created);
        """)

    # ── 笔记索引操作 ──

    def insert_note(self, title: str, file_path: str, tags: str, type: str,
                    project: str, status: str, created: str, updated: str,
                    word_count: int = 0, checksum: str | None = None) -> int:
        """插入笔记记录，返回 row id。"""
        self._ensure_connected()
        cursor = self.conn.execute(
            """INSERT INTO notes (title, file_path, tags, type, project, status,
                                  created, updated, word_count, checksum)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, file_path, tags, type, project or None, status,
             created, updated, word_count, checksum)
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_note(self, note_id: int, **kwargs) -> bool:
        """根据笔记 id 更新元数据。只更新 kwargs 中已存在的合法列名。"""
        self._ensure_connected()
        if not kwargs:
            return False

        allowed = {"title", "file_path", "tags", "type", "project",
                   "status", "created", "updated", "word_count", "checksum"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [note_id]
        cursor = self.conn.execute(
            f"UPDATE notes SET {set_clause} WHERE id = ?", values
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_note(self, file_path: str) -> bool:
        """删除笔记记录及其 FTS 索引和关联 wikilinks。"""
        self._ensure_connected()
        row = self.conn.execute(
            "SELECT id FROM notes WHERE file_path = ?", (file_path,)
        ).fetchone()
        if row is None:
            return False

        note_id = row["id"]
        self.conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
        self.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self.conn.execute(
            "DELETE FROM wikilinks WHERE source_path = ? OR target_path = ?",
            (file_path, file_path)
        )
        self.conn.commit()
        return True

    def get_note_by_path(self, file_path: str) -> dict | None:
        """根据文件路径查询笔记。"""
        self._ensure_connected()
        row = self.conn.execute(
            "SELECT * FROM notes WHERE file_path = ?", (file_path,)
        ).fetchone()
        return dict(row) if row else None

    def get_note_by_title(self, title: str) -> dict | None:
        """根据标题查询笔记。"""
        self._ensure_connected()
        row = self.conn.execute(
            "SELECT * FROM notes WHERE title = ?", (title,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_titles(self) -> list[str]:
        """返回所有笔记标题，用于 wikilink 匹配和自动补全。"""
        self._ensure_connected()
        rows = self.conn.execute("SELECT title FROM notes").fetchall()
        return [row["title"] for row in rows]

    # ── FTS5 全文搜索 ──

    def search(self, query: str, tags: str | None = None,
               project: str | None = None, type: str | None = None,
               limit: int = 10, offset: int = 0) -> list[dict]:
        """BM25 排序的全文搜索。

        对 notes_fts 虚拟表进行 FTS5 查询，JOIN notes 获取元数据。
        返回包含 title/snippet/tags/created/path/score 的结果列表。
        """
        self._ensure_connected()
        where_clauses = []
        params: list = []

        # 构建 FTS5 查询（冒号分割短语精确匹配，OR 连接词级匹配）
        if query.strip():
            terms = [f'"{term}"' if " " in term else term
                     for term in query.strip().split()]
            fts_query = " OR ".join(terms) if terms else query.strip()
            where_clauses.append("notes_fts MATCH ?")
            params.append(fts_query)
        else:
            return []

        # notes 表辅助过滤条件
        note_filters = []
        if tags:
            for tag in [t.strip() for t in tags.split(",") if t.strip()]:
                note_filters.append("notes.tags LIKE ?")
                params.append(f"%{tag}%")
        if project:
            note_filters.append("notes.project = ?")
            params.append(project)
        if type:
            note_filters.append("notes.type = ?")
            params.append(type)

        note_filter_str = " AND ".join(note_filters) if note_filters else "1=1"

        sql = f"""
            SELECT notes.id, notes.title, notes.tags, notes.type, notes.project,
                   notes.status, notes.created, notes.updated, notes.file_path,
                   snippet(notes_fts, 1, '<mark>', '</mark>', '...', 40) AS snippet,
                   rank AS score
            FROM notes_fts
            JOIN notes ON notes_fts.rowid = notes.id
            WHERE {where_clauses[0]} AND {note_filter_str}
            ORDER BY bm25(notes_fts)
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        rows = self.conn.execute(sql, params).fetchall()

        return [
            {
                "title": row["title"],
                "snippet": row["snippet"] or "",
                "tags": row["tags"] or "",
                "type": row["type"],
                "project": row["project"] or "",
                "created": row["created"],
                "path": row["file_path"],
                "score": round(row["score"], 4) if row["score"] else 0,
            }
            for row in rows
        ]

    def reindex_note(self, note_id: int, title: str, content: str):
        """更新单条笔记的 FTS5 全文索引。先删旧索引后插入新内容。"""
        self._ensure_connected()
        self.conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
        self.conn.execute(
            "INSERT INTO notes_fts(rowid, title, content) VALUES (?, ?, ?)",
            (note_id, title, content)
        )
        self.conn.commit()

    def build_full_index(self, vault_dir: Path) -> int:
        """全量重建 FTS5 索引。

        遍历 vault_dir 下所有 .md 文件，收集 (rowid, title, content) 元组，
        再用 executemany 批量写入 notes_fts。已有 notes 记录的文件关联已有 id。
        返回已索引的文件数。
        """
        self._ensure_connected()
        vault_dir = Path(vault_dir).expanduser().resolve()

        # 清空现有索引
        self.conn.execute("DELETE FROM notes_fts")

        md_files = list(vault_dir.rglob("*.md"))
        batch_data: list[tuple[int, str, str]] = []

        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            rel_path = str(md_file.relative_to(vault_dir)).replace("\\", "/")
            title = md_file.stem

            # 检查 notes 表中是否已存在
            row = self.conn.execute(
                "SELECT id FROM notes WHERE file_path = ?", (rel_path,)
            ).fetchone()

            if row:
                batch_data.append((row["id"], title, content))

        # 批量 INSERT 避免逐行提交开销
        if batch_data:
            self.conn.executemany(
                "INSERT INTO notes_fts(rowid, title, content) VALUES (?, ?, ?)",
                batch_data,
            )

        self.conn.commit()
        return len(batch_data)

    # ── 标签索引 ──

    def update_tags(self, tags: list[str]):
        """批量更新标签使用计数。新标签插入，已有标签计数 +1 并更新 last_used。"""
        self._ensure_connected()
        now = datetime.now().strftime("%Y-%m-%d")
        for tag in tags:
            tag = tag.strip()
            if not tag:
                continue
            self.conn.execute(
                """INSERT INTO tag_index (tag, count, last_used) VALUES (?, 1, ?)
                   ON CONFLICT(tag) DO UPDATE SET count = count + 1, last_used = ?""",
                (tag, now, now)
            )
        self.conn.commit()

    def get_all_tags(self, query: str | None = None) -> list[dict]:
        """获取标签列表，按使用频次降序。可选 keyword 模糊搜索。"""
        self._ensure_connected()
        if query:
            rows = self.conn.execute(
                """SELECT tag, count, last_used FROM tag_index
                   WHERE tag LIKE ? ORDER BY count DESC""",
                (f"%{query}%",)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT tag, count, last_used FROM tag_index ORDER BY count DESC"
            ).fetchall()
        return [
            {"tag": row["tag"], "count": row["count"], "last_used": row["last_used"]}
            for row in rows
        ]

    def rebuild_tag_index(self) -> int:
        """全量重建 tag_index 表。

        解析 notes 表所有笔记的 tags JSON 字段，重新统计每个标签的出现次数
        和最近使用日期。先清空 tag_index，再批量写入。
        返回重建的标签条目数。
        """
        self._ensure_connected()

        # 清空现有标签索引
        self.conn.execute("DELETE FROM tag_index")

        rows = self.conn.execute(
            "SELECT tags, updated FROM notes WHERE tags IS NOT NULL AND tags != ''"
        ).fetchall()

        tag_stats: dict[str, tuple[int, str]] = {}  # tag → (count, last_used)

        for row in rows:
            tags_str = row["tags"]
            updated = row["updated"]
            try:
                tag_list = json.loads(tags_str)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(tag_list, list):
                continue
            for tag in tag_list:
                tag = tag.strip()
                if not tag:
                    continue
                if tag in tag_stats:
                    cnt, prev_date = tag_stats[tag]
                    new_date = updated if updated > prev_date else prev_date
                    tag_stats[tag] = (cnt + 1, new_date)
                else:
                    tag_stats[tag] = (1, updated)

        # 批量 INSERT，一次性提交
        batch_data = [
            (tag, cnt, last_used) for tag, (cnt, last_used) in tag_stats.items()
        ]
        if batch_data:
            self.conn.executemany(
                "INSERT INTO tag_index (tag, count, last_used) VALUES (?, ?, ?)",
                batch_data,
            )

        self.conn.commit()
        return len(batch_data)

    # ── wikilink 引用图 ──

    def update_wikilinks(self, source_path: str, target_paths: list[str],
                         context: str | None = None):
        """替换某篇笔记的出站 wikilink 记录。先删旧，再批量写入。"""
        self._ensure_connected()
        self.conn.execute(
            "DELETE FROM wikilinks WHERE source_path = ?", (source_path,)
        )
        for target in target_paths:
            self.conn.execute(
                """INSERT OR IGNORE INTO wikilinks (source_path, target_path, context)
                   VALUES (?, ?, ?)""",
                (source_path, target, context)
            )
        self.conn.commit()

    def get_wikilink_graph(self) -> dict:
        """返回完整引用图，仅包含 notes 表中实际存在的笔记。

        Returns:
            {source_path: [target_path, ...], ...}
        """
        self._ensure_connected()
        rows = self.conn.execute(
            """SELECT w.source_path, w.target_path
               FROM wikilinks w
               JOIN notes n1 ON w.source_path = n1.file_path
               JOIN notes n2 ON w.target_path = n2.file_path"""
        ).fetchall()

        graph: dict[str, set[str]] = {}
        for row in rows:
            src, tgt = row["source_path"], row["target_path"]
            graph.setdefault(src, set()).add(tgt)
        return {k: list(v) for k, v in graph.items()}

    # ── graphify 构建记录 ──

    def record_graphify_build(self, project: str, node_count: int,
                              edge_count: int, community_count: int,
                              commit_sha: str | None = None) -> int:
        """记录一次 graphify 代码图谱构建。"""
        self._ensure_connected()
        built_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.conn.execute(
            """INSERT INTO graphify_builds (project, commit_sha, node_count,
                                           edge_count, community_count, built_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project, commit_sha, node_count, edge_count, community_count, built_at)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_latest_graphify_build(self, project: str) -> dict | None:
        """获取指定项目最近一次 graphify 构建记录。"""
        self._ensure_connected()
        row = self.conn.execute(
            """SELECT * FROM graphify_builds
               WHERE project = ?
               ORDER BY built_at DESC LIMIT 1""",
            (project,)
        ).fetchone()
        return dict(row) if row else None

    # ── 会话日志 ──

    def insert_session_log(self, project: str, date: str, file_path: str,
                           summary: str, decisions: str | None = None,
                           todos: str | None = None) -> int:
        """插入一条会话日志记录。"""
        self._ensure_connected()
        cursor = self.conn.execute(
            """INSERT INTO session_logs (project, date, file_path, summary,
                                         decisions, todos)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project, date, file_path, summary, decisions, todos)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_recent_logs(self, project: str, count: int = 3) -> list[dict]:
        """获取指定项目最近 N 条会话日志，按日期降序。"""
        self._ensure_connected()
        rows = self.conn.execute(
            """SELECT * FROM session_logs
               WHERE project = ?
               ORDER BY date DESC LIMIT ?""",
            (project, count)
        ).fetchall()
        return [dict(row) for row in rows]

    def update_note_content(self, file_path: str, content: str) -> bool:
        """更新笔记正文并重建 FTS5 索引。按 file_path 定位笔记。"""
        self._ensure_connected()
        row = self.conn.execute(
            "SELECT id, title FROM notes WHERE file_path = ?", (file_path,)
        ).fetchone()
        if not row:
            return False
        note_id, title = row["id"], row["title"]
        today = date.today().isoformat()
        self.conn.execute(
            "UPDATE notes SET updated = ?, word_count = ?, checksum = ? WHERE id = ?",
            (today, len(content.split()), hashlib.sha256(content.encode()).hexdigest(), note_id),
        )
        self.reindex_note(note_id, title, content)
        return True

    def list_notes(self, tags: list[str] | None = None, project: str | None = None,
                   note_type: str | None = None, status: str | None = None,
                   sort: str = "updated", limit: int = 20, offset: int = 0) -> list[dict]:
        """按条件列出笔记，支持分页排序。"""
        self._ensure_connected()
        clauses = ["1=1"]
        params: list = []
        if tags:
            for tag in tags:
                clauses.append("tags LIKE ?")
                params.append(f"%{tag}%")
        if project:
            clauses.append("project = ?")
            params.append(project)
        if note_type:
            clauses.append("type = ?")
            params.append(note_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        sort_col = {"updated": "updated", "created": "created", "title": "title"}.get(sort, "updated")
        sql = f"SELECT * FROM notes WHERE {' AND '.join(clauses)} ORDER BY {sort_col} DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def find_orphans(self) -> dict:
        """检测孤立笔记（入度或出度为零）。"""
        self._ensure_connected()
        no_incoming = self.conn.execute(
            """SELECT n.* FROM notes n
               WHERE n.file_path NOT IN (SELECT DISTINCT target_path FROM wikilinks)
               AND n.type != 'session-log'"""
        ).fetchall()
        no_outgoing = self.conn.execute(
            """SELECT n.* FROM notes n
               WHERE n.file_path NOT IN (SELECT DISTINCT source_path FROM wikilinks)
               AND n.type != 'session-log'"""
        ).fetchall()
        return {"no_incoming": [dict(r) for r in no_incoming], "no_outgoing": [dict(r) for r in no_outgoing]}

    def get_recent_architecture_notes(self, project: str, limit: int = 5) -> list[dict]:
        """获取项目最近架构笔记（permanent/solution 类型）。"""
        self._ensure_connected()
        rows = self.conn.execute(
            """SELECT * FROM notes WHERE project = ? AND type IN ('permanent', 'solution')
               ORDER BY updated DESC LIMIT ?""",
            (project, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 统计 ──

    def get_stats(self) -> dict:
        """返回知识库统计面板。

        Returns:
            {total_notes, by_type, by_project, top_tags, recent_count,
             total_wikilinks, avg_links}
        """
        self._ensure_connected()

        total_notes = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM notes"
        ).fetchone()["cnt"]

        type_rows = self.conn.execute(
            "SELECT type, COUNT(*) as cnt FROM notes GROUP BY type ORDER BY cnt DESC"
        ).fetchall()
        by_type = {row["type"]: row["cnt"] for row in type_rows}

        project_rows = self.conn.execute(
            """SELECT COALESCE(project, '未分类') as proj, COUNT(*) as cnt
               FROM notes GROUP BY project ORDER BY cnt DESC"""
        ).fetchall()
        by_project = {row["proj"]: row["cnt"] for row in project_rows}

        tag_rows = self.conn.execute(
            "SELECT tag, count FROM tag_index ORDER BY count DESC LIMIT 10"
        ).fetchall()
        top_tags = [{"tag": row["tag"], "count": row["count"]} for row in tag_rows]

        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        recent_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM notes WHERE created >= ?", (week_ago,)
        ).fetchone()["cnt"]

        total_wikilinks = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM wikilinks"
        ).fetchone()["cnt"]

        avg_links = round(total_wikilinks / total_notes, 2) if total_notes > 0 else 0

        return {
            "total_notes": total_notes,
            "by_type": by_type,
            "by_project": by_project,
            "top_tags": top_tags,
            "recent_count": recent_count,
            "total_wikilinks": total_wikilinks,
            "avg_links": avg_links,
        }
