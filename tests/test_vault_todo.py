"""待办工具集成测试。"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from db import VaultDB


class _SharedVaultDB(VaultDB):
    """共享连接的 VaultDB。"""

    @classmethod
    def create_shared(cls, db_path):
        inst = cls(db_path)
        inst._connect()
        return inst

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def _real_close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


class TestVaultTodo(unittest.TestCase):
    """待办工具测试。"""

    @classmethod
    def setUpClass(cls):
        cls.vault_dir = Path.home() / "vault-e2e-test"
        import shutil
        if cls.vault_dir.exists():
            shutil.rmtree(cls.vault_dir, ignore_errors=True)
        cls.vault_dir.mkdir(parents=True, exist_ok=True)
        cls.db_path = cls.vault_dir / "test_vault.db"
        if cls.db_path.exists():
            cls.db_path.unlink()
        cls._shared_db = _SharedVaultDB.create_shared(cls.db_path)
        cls._shared_db.initialize()

        _todo_modules = [
            "tools.vault_todo_list", "tools.vault_todo_done",
            "tools.vault_todo_progress", "tools.vault_todo_pending",
            "tools.vault_todo_delete",
        ]
        cls._patches = [
            patch(f"{mod}.VaultDB", lambda: cls._shared_db) for mod in _todo_modules
        ]
        cls._vaultdir_patch = patch("tools._shared.DEFAULT_VAULT_DIR", cls.vault_dir)
        for p in cls._patches:
            p.start()
        cls._vaultdir_patch.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()
        cls._vaultdir_patch.stop()
        cls._shared_db._real_close()
        import shutil
        shutil.rmtree(cls.vault_dir, ignore_errors=True)

    def setUp(self):
        for table in ["todos", "notes", "tag_index", "wikilinks", "session_logs", "graphify_builds"]:
            self._shared_db.conn.execute(f"DELETE FROM {table}")
        self._shared_db.conn.execute("DELETE FROM notes_fts")
        self._shared_db.conn.commit()

    def _parse(self, result):
        return json.loads(result[0].text)

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def _insert_todo(self, content="测试待办", project="test-project"):
        return self._shared_db.insert_todo(project, content)

    def _vault_dir(self):
        self._shared_db.conn.execute("INSERT INTO notes (title, file_path, type, created, updated) VALUES ('x','x.md','permanent','2025-01-01','2025-01-01')")
        self._shared_db.conn.commit()

    def test_todo_list_empty(self):
        from tools.vault_todo_list import handle_todo_list
        result = self._run(handle_todo_list({"project": "empty-project"}))
        data = self._parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(len(data["todos"]), 0)

    def test_todo_list_with_items(self):
        self._insert_todo("待办A")
        self._insert_todo("待办B")
        from tools.vault_todo_list import handle_todo_list
        result = self._run(handle_todo_list({"project": "test-project"}))
        data = self._parse(result)
        self.assertEqual(data["count"], 2)

    def test_todo_done(self):
        tid = self._insert_todo("待完成")
        from tools.vault_todo_done import handle_todo_done
        result = self._run(handle_todo_done({"id": tid}))
        data = self._parse(result)
        self.assertEqual(data["status"], "ok")
        todos = self._shared_db.list_todos("test-project", status="done")
        self.assertEqual(len(todos), 1)

    def test_todo_progress(self):
        tid = self._insert_todo("进行中")
        from tools.vault_todo_progress import handle_todo_progress
        result = self._run(handle_todo_progress({"id": tid}))
        data = self._parse(result)
        self.assertEqual(data["status"], "ok")
        todos = self._shared_db.list_todos("test-project", status="in-progress")
        self.assertEqual(len(todos), 1)

    def test_todo_pending(self):
        tid = self._insert_todo("恢复")
        self._shared_db.update_todo_status(tid, "done")
        from tools.vault_todo_pending import handle_todo_pending
        result = self._run(handle_todo_pending({"id": tid}))
        data = self._parse(result)
        self.assertEqual(data["status"], "ok")
        todos = self._shared_db.list_todos("test-project", status="pending")
        self.assertEqual(len(todos), 1)

    def test_todo_delete(self):
        tid = self._insert_todo("删除项")
        from tools.vault_todo_delete import handle_todo_delete
        result = self._run(handle_todo_delete({"id": tid}))
        data = self._parse(result)
        self.assertEqual(data["status"], "ok")
        todos = self._shared_db.list_todos("test-project")
        self.assertEqual(len(todos), 0)

    def test_todo_done_missing_id(self):
        from tools.vault_todo_done import handle_todo_done
        result = self._run(handle_todo_done({}))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")

    def test_upsert_todo_skips_duplicate(self):
        tid1 = self._shared_db.upsert_todo("test-project", "重复待办")
        tid2 = self._shared_db.upsert_todo("test-project", "重复待办")
        self.assertGreater(tid1, 0)
        self.assertEqual(tid2, 0)

    def test_upsert_todo_allows_after_done(self):
        tid1 = self._shared_db.upsert_todo("test-project", "再添加")
        self._shared_db.update_todo_status(tid1, "done")
        tid2 = self._shared_db.upsert_todo("test-project", "再添加")
        self.assertGreater(tid2, 0)

    def test_count_by_status(self):
        self._insert_todo("A")
        self._insert_todo("B")
        tid = self._insert_todo("C")
        self._shared_db.update_todo_status(tid, "done")
        counts = self._shared_db.count_by_status("test-project")
        self.assertEqual(counts.get("pending", 0), 2)
        self.assertEqual(counts.get("done", 0), 1)
