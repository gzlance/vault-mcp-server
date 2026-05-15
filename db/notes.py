"""笔记 CRUD + FTS5 全文搜索 + 标签统计。"""

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path


class NotesOperations:
    """笔记和标签的数据库操作。

    期望宿主类（通过多重继承）提供:
      - self.conn: sqlite3.Connection
      - self._ensure_connected()
    """

    # ── 笔记 CRUD ──

    def insert_note(
        self,
        title: str,
        file_path: str,
        tags: str,
        type: str,
        project: str,
        created: str,
        updated: str,
        word_count: int = 0,
        checksum: str | None = None,
    ) -> int:
        """插入笔记记录，返回 row id（v2.0 移除 status 参数）。"""
        self._ensure_connected()
        cursor = self.conn.execute(
            """INSERT INTO notes (title, file_path, tags, type, project,
                                  created, updated, word_count, checksum)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, file_path, tags, type, project or None, created, updated, word_count, checksum),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_note(self, note_id: int, **kwargs) -> bool:
        """根据 id 更新元数据，只更新合法列名（v2.0 移除 status）。"""
        self._ensure_connected()
        if not kwargs:
            return False
        allowed = {
            "title", "file_path", "tags", "type", "project",
            "created", "updated", "word_count", "checksum",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [note_id]
        cursor = self.conn.execute(f"UPDATE notes SET {set_clause} WHERE id = ?", values)
        self.conn.commit()
        return cursor.rowcount > 0

    def update_note_by_title_project(self, title: str, project: str, **kwargs) -> bool:
        """v2.0 新增: 按标题 + project 作用域更新（WHERE title=? AND project=?）。"""
        self._ensure_connected()
        allowed = {
            "title", "file_path", "tags", "type", "project",
            "created", "updated", "word_count", "checksum",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [title, project or ""]
        cursor = self.conn.execute(
            f"UPDATE notes SET {set_clause} WHERE title = ? AND project = ?", values
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_note(self, file_path: str) -> dict | None:
        """删除笔记及其 FTS 索引 + wikilink 引用，返回被删笔记元数据（v2.0 返回 dict）。"""
        self._ensure_connected()
        row = self.conn.execute(
            "SELECT * FROM notes WHERE file_path = ?", (file_path,)
        ).fetchone()
        if row is None:
            return None
        deleted = dict(row)
        note_id = row["id"]
        self.conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
        self.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self.conn.execute(
            "DELETE FROM wikilinks WHERE source_path = ? OR target_path = ?", (file_path, file_path)
        )
        self.conn.commit()
        return deleted

    def get_note_by_path(self, file_path: str) -> dict | None:
        self._ensure_connected()
        row = self.conn.execute(
            "SELECT * FROM notes WHERE file_path = ?", (file_path,)
        ).fetchone()
        return dict(row) if row else None

    def get_note_by_title(self, title: str) -> dict | None:
        self._ensure_connected()
        row = self.conn.execute(
            "SELECT * FROM notes WHERE title = ?", (title,)
        ).fetchone()
        return dict(row) if row else None

    def get_note_by_title_project(self, title: str, project: str) -> dict | None:
        """v2.0 新增: project 作用域内精确匹配。"""
        self._ensure_connected()
        row = self.conn.execute(
            "SELECT * FROM notes WHERE title = ? AND project = ?", (title, project or "")
        ).fetchone()
        return dict(row) if row else None

    def get_all_titles(self, project: str | None = None) -> list[str]:
        """返回笔记标题列表，v2.0 新增可选 project 过滤。"""
        self._ensure_connected()
        if project is not None:
            rows = self.conn.execute(
                "SELECT title FROM notes WHERE project = ?", (project,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT title FROM notes").fetchall()
        return [row["title"] for row in rows]

    def update_note_content(self, file_path: str, content: str) -> bool:
        """更新正文并重建 FTS5 索引。"""
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

    def list_notes(
        self,
        tags: list[str] | None = None,
        project: str | None = None,
        note_type: str | None = None,
        sort: str = "updated",
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """按条件列出笔记（v2.0 移除 status 参数）。"""
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
        sort_col = {"updated": "updated", "created": "created", "title": "title"}.get(sort, "updated")
        sql = (
            f"SELECT * FROM notes WHERE {' AND '.join(clauses)}"
            f" ORDER BY {sort_col} DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def get_recent_architecture_notes(self, project: str, limit: int = 5) -> list[dict]:
        self._ensure_connected()
        rows = self.conn.execute(
            """SELECT * FROM notes WHERE project = ? AND type IN ('permanent', 'solution')
               ORDER BY updated DESC LIMIT ?""",
            (project, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── FTS5 全文搜索 ──

    def search(
        self,
        query: str,
        tags: str | None = None,
        project: str | None = None,
        type: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict]:
        """BM25 排序的全文搜索。"""
        self._ensure_connected()
        where_clauses = []
        params: list = []

        if query.strip():
            terms = [f'"{term}"' if " " in term else term for term in query.strip().split()]
            fts_query = " OR ".join(terms) if terms else query.strip()
            where_clauses.append("notes_fts MATCH ?")
            params.append(fts_query)
        else:
            return []

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
                   notes.created, notes.updated, notes.file_path,
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

    def search_by_title_fuzzy(
        self, title: str, project: str | None = None, limit: int = 5
    ) -> list[dict]:
        """v2.0 新增: FTS5 标题模糊搜索（供 resolver.py 第三级使用）。"""
        self._ensure_connected()
        terms = " OR ".join(title.strip().split())
        where = "notes_fts MATCH ?"
        params: list = [terms]
        if project:
            where += " AND notes.project = ?"
            params.append(project)
        sql = f"""
            SELECT notes.id, notes.title, notes.type, notes.project,
                   notes.file_path, notes.created, notes.updated,
                   rank AS score
            FROM notes_fts
            JOIN notes ON notes_fts.rowid = notes.id
            WHERE {where}
            ORDER BY bm25(notes_fts)
            LIMIT ?
        """
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def reindex_note(self, note_id: int, title: str, content: str) -> None:
        self._ensure_connected()
        self.conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
        self.conn.execute(
            "INSERT INTO notes_fts(rowid, title, content) VALUES (?, ?, ?)",
            (note_id, title, content),
        )
        self.conn.commit()

    def build_full_index(self, vault_dir: Path) -> int:
        """全量重建 FTS5 索引。"""
        self._ensure_connected()
        vault_dir = Path(vault_dir).expanduser().resolve()
        self.conn.execute("DELETE FROM notes_fts")
        md_files = list(vault_dir.rglob("*.md"))
        batch_data: list[tuple[int, str, str]] = []
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            rel_path = str(md_file.relative_to(vault_dir)).replace("\\", "/")
            row = self.conn.execute(
                "SELECT id FROM notes WHERE file_path = ?", (rel_path,)
            ).fetchone()
            if row:
                batch_data.append((row["id"], md_file.stem, content))
        if batch_data:
            self.conn.executemany(
                "INSERT INTO notes_fts(rowid, title, content) VALUES (?, ?, ?)", batch_data
            )
        self.conn.commit()
        return len(batch_data)

    # ── 标签索引 ──

    def update_tags(self, tags: list[str]) -> None:
        self._ensure_connected()
        now = datetime.now().strftime("%Y-%m-%d")
        for tag in tags:
            tag = tag.strip()
            if not tag:
                continue
            self.conn.execute(
                """INSERT INTO tag_index (tag, count, last_used) VALUES (?, 1, ?)
                   ON CONFLICT(tag) DO UPDATE SET count = count + 1, last_used = ?""",
                (tag, now, now),
            )
        self.conn.commit()

    def get_all_tags(self, query: str | None = None) -> list[dict]:
        self._ensure_connected()
        if query:
            rows = self.conn.execute(
                "SELECT tag, count, last_used FROM tag_index WHERE tag LIKE ? ORDER BY count DESC",
                (f"%{query}%",),
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
        """全量重建 tag_index。"""
        self._ensure_connected()
        self.conn.execute("DELETE FROM tag_index")
        rows = self.conn.execute(
            "SELECT tags, updated FROM notes WHERE tags IS NOT NULL AND tags != ''"
        ).fetchall()
        tag_stats: dict[str, tuple[int, str]] = {}
        for row in rows:
            try:
                tag_list = json.loads(row["tags"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(tag_list, list):
                continue
            for tag in tag_list:
                tag = tag.strip()
                if not tag:
                    continue
                if tag in tag_stats:
                    cnt, prev = tag_stats[tag]
                    tag_stats[tag] = (cnt + 1, row["updated"] if row["updated"] > prev else prev)
                else:
                    tag_stats[tag] = (1, row["updated"])
        batch_data = [(t, c, u) for t, (c, u) in tag_stats.items()]
        if batch_data:
            self.conn.executemany(
                "INSERT INTO tag_index (tag, count, last_used) VALUES (?, ?, ?)", batch_data
            )
        self.conn.commit()
        return len(batch_data)

    # ── v2.0 新增: 标签重叠检测 ──

    def find_tag_overlaps(self, tags: list[str], project: str) -> list[dict]:
        """检测同 project 内标签重叠的笔记（json_each 交集，不走 FTS5）。

        Returns: [{"title": ..., "file_path": ..., "overlap_count": ..., "overlapping_tags": [...]}, ...]
        """
        self._ensure_connected()
        if not tags:
            return []
        placeholders = ", ".join("?" for _ in tags)
        sql = f"""
            SELECT n.title, n.file_path, n.tags,
                   COUNT(*) as overlap_count
            FROM notes n, json_each(n.tags)
            WHERE json_each.value IN ({placeholders})
              AND n.project = ?
            GROUP BY n.file_path
            HAVING overlap_count >= 3
            ORDER BY overlap_count DESC
        """
        rows = self.conn.execute(sql, [*tags, project or ""]).fetchall()
        result = []
        for row in rows:
            try:
                note_tags = json.loads(row["tags"])
            except (json.JSONDecodeError, TypeError):
                note_tags = []
            overlapping = [t for t in tags if t in note_tags]
            result.append({
                "title": row["title"],
                "file_path": row["file_path"],
                "overlap_count": row["overlap_count"],
                "overlapping_tags": overlapping,
            })
        return result

    # ── 统计 ──

    def get_stats(self) -> dict:
        self._ensure_connected()
        total_notes = self.conn.execute("SELECT COUNT(*) as cnt FROM notes").fetchone()["cnt"]
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
        total_wikilinks = self.conn.execute("SELECT COUNT(*) as cnt FROM wikilinks").fetchone()["cnt"]
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

    def find_orphans(self) -> dict:
        """检测孤立笔记（入度或出度为零）。排除 session-log 类型。"""
        self._ensure_connected()
        no_incoming = self.conn.execute("""SELECT n.* FROM notes n
               WHERE n.file_path NOT IN (SELECT DISTINCT target_path FROM wikilinks)
               AND n.type != 'session-log'""").fetchall()
        no_outgoing = self.conn.execute("""SELECT n.* FROM notes n
               WHERE n.file_path NOT IN (SELECT DISTINCT source_path FROM wikilinks)
               AND n.type != 'session-log'""").fetchall()
        return {
            "no_incoming": [dict(r) for r in no_incoming],
            "no_outgoing": [dict(r) for r in no_outgoing],
        }
