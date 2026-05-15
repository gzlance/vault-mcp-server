"""wikilink 双向引用图操作。"""


class WikilinkOperations:
    """wikilinks 表操作。

    期望宿主类提供: self.conn, self._ensure_connected()
    """

    def update_wikilinks(
        self, source_path: str, target_paths: list[str], context: str | None = None
    ) -> None:
        """替换某篇笔记的出站 wikilink 记录。"""
        self._ensure_connected()
        self.conn.execute("DELETE FROM wikilinks WHERE source_path = ?", (source_path,))
        for target in target_paths:
            self.conn.execute(
                "INSERT OR IGNORE INTO wikilinks (source_path, target_path, context) VALUES (?, ?, ?)",
                (source_path, target, context),
            )
        self.conn.commit()

    def get_wikilink_graph(self) -> dict:
        """返回完整引用图（仅含 notes 表中实际存在的笔记）。

        Returns: {source_path: [target_path, ...], ...}
        """
        self._ensure_connected()
        rows = self.conn.execute("""SELECT w.source_path, w.target_path
               FROM wikilinks w
               JOIN notes n1 ON w.source_path = n1.file_path
               JOIN notes n2 ON w.target_path = n2.file_path""").fetchall()
        graph: dict[str, set[str]] = {}
        for row in rows:
            src, tgt = row["source_path"], row["target_path"]
            graph.setdefault(src, set()).add(tgt)
        return {k: list(v) for k, v in graph.items()}
