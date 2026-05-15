"""待办 CRUD（v2.0 新增）。"""


class TodosOperations:
    """todos 表操作。

    期望宿主类提供: self.conn, self._ensure_connected()
    """

    def insert_todo(
        self, project: str, content: str, source_log_id: int | None = None
    ) -> int:
        """插入待办，默认 status='pending'。"""
        self._ensure_connected()
        cursor = self.conn.execute(
            "INSERT INTO todos (project, content, source_log_id) VALUES (?, ?, ?)",
            (project, content, source_log_id),
        )
        self.conn.commit()
        return cursor.lastrowid

    def upsert_todo(
        self, project: str, content: str, source_log_id: int | None = None
    ) -> int:
        """同 project+content+pending 已存在则跳过，否则 INSERT。返回 0 或 rowid。"""
        self._ensure_connected()
        existing = self.conn.execute(
            "SELECT id FROM todos WHERE project = ? AND content = ? AND status = 'pending'",
            (project, content),
        ).fetchone()
        if existing:
            return 0  # 跳过，不重复创建
        cursor = self.conn.execute(
            "INSERT INTO todos (project, content, source_log_id) VALUES (?, ?, ?)",
            (project, content, source_log_id),
        )
        self.conn.commit()
        return cursor.lastrowid

    def list_todos(self, project: str, status: str | None = None) -> list[dict]:
        """列出项目待办，按 created 升序。"""
        self._ensure_connected()
        if status:
            rows = self.conn.execute(
                "SELECT * FROM todos WHERE project = ? AND status = ? ORDER BY created ASC",
                (project, status),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM todos WHERE project = ? ORDER BY status, created ASC",
                (project,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_todo_status(self, todo_id: int, status: str) -> bool:
        """更新待办状态，自动更新 updated 时间戳。"""
        self._ensure_connected()
        from datetime import datetime
        cursor = self.conn.execute(
            "UPDATE todos SET status = ?, updated = ? WHERE id = ?",
            (status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), todo_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_todo(self, todo_id: int) -> bool:
        self._ensure_connected()
        cursor = self.conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def count_by_status(self, project: str) -> dict:
        """Returns: {pending: N, in-progress: N, done: N}"""
        self._ensure_connected()
        rows = self.conn.execute(
            """SELECT status, COUNT(*) as cnt FROM todos
               WHERE project = ? GROUP BY status""",
            (project,),
        ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}
