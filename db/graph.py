"""graphify 代码图谱构建记录。"""

from datetime import datetime


class GraphOperations:
    """graphify_builds 表操作。

    期望宿主类提供: self.conn, self._ensure_connected()
    """

    def record_graphify_build(
        self,
        project: str,
        node_count: int,
        edge_count: int,
        community_count: int,
        commit_sha: str | None = None,
    ) -> int:
        self._ensure_connected()
        built_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.conn.execute(
            """INSERT INTO graphify_builds (project, commit_sha, node_count,
                                           edge_count, community_count, built_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project, commit_sha, node_count, edge_count, community_count, built_at),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_latest_graphify_build(self, project: str) -> dict | None:
        self._ensure_connected()
        row = self.conn.execute(
            "SELECT * FROM graphify_builds WHERE project = ? ORDER BY built_at DESC LIMIT 1",
            (project,),
        ).fetchone()
        return dict(row) if row else None
