"""SQLite 连接生命周期管理 + 表结构初始化。"""

import sqlite3
from pathlib import Path


class ConnectionManager:
    """管理 SQLite 连接：创建、WAL 优化、迁移、上下文管理器。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
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

    def close(self) -> None:
        """手动关闭连接，提交未保存的事务。"""
        if self.conn:
            self.conn.commit()
            self.conn.close()
            self.conn = None

    def _connect(self) -> None:
        """建立连接，启用性能优化 PRAGMA。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA cache_size=-8000")  # 8MB 页面缓存
        self.conn.execute("PRAGMA mmap_size=268435456")  # 256MB 内存映射 I/O
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.row_factory = sqlite3.Row

    def _ensure_connected(self) -> None:
        """懒连接：仅在尚未连接时建立连接。"""
        if self.conn is None:
            self._connect()

    # ── 表结构初始化 ──

    def initialize(self) -> None:
        """CREATE TABLE IF NOT EXISTS（幂等）。"""
        self._ensure_connected()
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                file_path   TEXT NOT NULL UNIQUE,
                tags        TEXT,
                type        TEXT NOT NULL DEFAULT 'permanent',
                project     TEXT,
                created     TEXT NOT NULL,
                updated     TEXT NOT NULL,
                word_count  INTEGER DEFAULT 0,
                checksum    TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                title,
                content,
                tokenize='trigram'
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

            CREATE TABLE IF NOT EXISTS todos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project       TEXT NOT NULL,
                content       TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending', 'in-progress', 'done')),
                source_log_id INTEGER REFERENCES session_logs(id) ON DELETE SET NULL,
                created       TEXT DEFAULT (datetime('now')),
                updated       TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type);
            CREATE INDEX IF NOT EXISTS idx_notes_project ON notes(project);
            CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated);
            CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title);
            CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created);
            CREATE INDEX IF NOT EXISTS idx_wikilinks_source ON wikilinks(source_path);
            CREATE INDEX IF NOT EXISTS idx_wikilinks_target ON wikilinks(target_path);
            CREATE INDEX IF NOT EXISTS idx_session_logs_project ON session_logs(project);
            CREATE INDEX IF NOT EXISTS idx_session_logs_date ON session_logs(date);
            CREATE INDEX IF NOT EXISTS idx_graphify_builds_project_built_at ON graphify_builds(project, built_at);
            CREATE INDEX IF NOT EXISTS idx_todos_project ON todos(project);
            CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
            CREATE INDEX IF NOT EXISTS idx_todos_project_content ON todos(project, content);
        """)
