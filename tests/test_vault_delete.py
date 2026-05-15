"""vault_delete 工具测试。"""
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from db import VaultDB


class _SharedVaultDB(VaultDB):
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


class TestVaultDelete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vault_dir = Path.home() / "vault-e2e-test"
        if cls.vault_dir.exists():
            shutil.rmtree(cls.vault_dir, ignore_errors=True)
        cls.vault_dir.mkdir(parents=True, exist_ok=True)
        cls.db_path = cls.vault_dir / "test_vault.db"
        if cls.db_path.exists():
            cls.db_path.unlink()
        cls._shared_db = _SharedVaultDB.create_shared(cls.db_path)
        cls._shared_db.initialize()

        cls._patches = [
            patch("tools.vault_delete.VaultDB", lambda: cls._shared_db),
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

    def _create_note(self, title="测试删除", content="正文内容", project="test-project",
                     note_type="permanent", tags=None):
        if tags is None:
            tags = ["test"]
        file_path = f"{project}/architecture/{title}.md"
        file_path = file_path.lower().replace(" ", "-")
        note_dir = self.vault_dir / project / "architecture"
        note_dir.mkdir(parents=True, exist_ok=True)
        md_path = note_dir / f"{title}.md"
        import datetime
        today = datetime.date.today().isoformat()
        md_path.write_text(f"---\ntitle: \"{title}\"\ntags: {json.dumps(tags)}\ncreated: {today}\nupdated: {today}\ntype: {note_type}\n---\n\n{content}\n", encoding="utf-8")
        self._shared_db.insert_note(
            title=title, file_path=file_path, tags=json.dumps(tags),
            type=note_type, project=project, created=today, updated=today,
        )
        return title, file_path

    def test_delete_exact_match(self):
        title, fp = self._create_note("我的笔记")
        from tools.vault_delete import handle_delete
        result = self._run(handle_delete({"title": "我的笔记", "project": "test-project"}))
        data = self._parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["deleted"]["matched_by"], "exact")

    def test_delete_not_found(self):
        from tools.vault_delete import handle_delete
        result = self._run(handle_delete({"title": "不存在的笔记"}))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")

    def test_delete_missing_title(self):
        from tools.vault_delete import handle_delete
        result = self._run(handle_delete({}))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
