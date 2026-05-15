"""会话日志数据操作。"""


class SessionOperations:
    """session_logs 表 CRUD。

    期望宿主类提供: self.conn, self._ensure_connected()
    """

    def insert_session_log(
        self,
        project: str,
        date: str,
        file_path: str,
        summary: str,
        decisions: str | None = None,
        todos: str | None = None,
    ) -> int:
        self._ensure_connected()
        cursor = self.conn.execute(
            """INSERT INTO session_logs (project, date, file_path, summary, decisions, todos)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project, date, file_path, summary, decisions, todos),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_recent_logs(self, project: str, count: int = 3) -> list[dict]:
        self._ensure_connected()
        rows = self.conn.execute(
            "SELECT * FROM session_logs WHERE project = ? ORDER BY date DESC LIMIT ?",
            (project, count),
        ).fetchall()
        return [dict(row) for row in rows]
