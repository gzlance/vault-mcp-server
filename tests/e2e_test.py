"""Vault MCP Server — 端到端验证测试。

模拟完整知识库工作流：init → save×3 → search → list → stats → tags
→ update → log → resume → orphan → graphify_status → graphify_query → 幂等验证。

运行方式：
    cd C:/Users/Gzlance/scripts/vault-mcp-server
    python -m pytest tests/e2e_test.py -v
"""
import asyncio
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from db import VaultDB  # noqa: E402
from tools.vault_tools import (  # noqa: E402
    handle_init, handle_save, handle_search, handle_resume,
    handle_list, handle_stats, handle_orphan, handle_update,
    handle_tags, handle_log,
)
from tools.graphify_tools import (  # noqa: E402
    handle_graphify_build, handle_graphify_status, handle_graphify_query,
)


class _SharedVaultDB(VaultDB):
    """所有 handler 共享同一个 SQLite 连接，避免 Windows 文件锁定。"""

    _instance = None

    def __init__(self, db_path=None):
        pass

    @classmethod
    def create_shared(cls, db_path):
        cls._instance = object.__new__(cls)
        cls._instance.db_path = Path(db_path)
        cls._instance.conn = None
        cls._instance._connect()
        cls._instance.initialize()
        return cls._instance

    def _connect(self):
        if self.conn is not None:
            return
        import sqlite3
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row

    def _ensure_connected(self):
        if self.conn is None:
            self._connect()

    def __enter__(self):
        self._ensure_connected()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            try:
                self.conn.commit()
            except Exception:
                pass
        else:
            try:
                self.conn.rollback()
            except Exception:
                pass
        return False

    def close(self):
        pass

    def _real_close(self):
        if self.conn:
            try:
                self.conn.commit()
            except Exception:
                pass
            self.conn.close()
            self.conn = None


def _parse(result):
    return json.loads(result[0].text)


class TestE2EFullFlow(unittest.TestCase):
    """端到端测试：14 步完整知识库工作流。"""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = Path.home() / "vault-e2e-test"
        cls.db_path = cls.tmpdir / "vault.db"

        if cls.tmpdir.exists():
            shutil.rmtree(cls.tmpdir, ignore_errors=True)
        cls.tmpdir.mkdir(parents=True, exist_ok=True)

        cls._shared_db = _SharedVaultDB.create_shared(cls.db_path)

        cls._vaultdb_patch = patch(
            "tools.vault_tools.VaultDB",
            lambda: cls._shared_db,
        )
        cls._vaultdb_gt_patch = patch(
            "tools.graphify_tools.VaultDB",
            lambda: cls._shared_db,
        )
        cls._vaultdir_patch = patch(
            "tools._shared.DEFAULT_VAULT_DIR",
            cls.tmpdir,
        )
        cls._vaultdb_patch.start()
        cls._vaultdb_gt_patch.start()
        cls._vaultdir_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._vaultdb_patch.stop()
        cls._vaultdb_gt_patch.stop()
        cls._vaultdir_patch.stop()

        cls._shared_db._real_close()

        shutil.rmtree(str(cls.tmpdir), ignore_errors=True)

    # ── 步骤 1: vault_init ──

    def test_step01_init(self):
        result = asyncio.run(handle_init({}))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(len(data["actions"]), 3)
        for sub in ["permanent", "templates", "logs", "graphify"]:
            self.assertTrue((self.tmpdir / sub).is_dir())
        self.assertTrue((self.tmpdir / "templates" / "default-note.md").exists())
        self.assertTrue((self.tmpdir / "templates" / "session-log.md").exists())

    # ── 步骤 2-4: vault_save ×3 ──

    def test_step02_save_python_note(self):
        result = asyncio.run(handle_save({
            "title": "Python Async",
            "content": "asyncio is Python's async I/O library.\n\nUse async/await for concurrency.",
            "tags": ["python", "async", "concurrency"],
            "type": "permanent",
            "status": "draft",
        }))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["action"], "created")
        self.assertIn("permanent", data["file_path"])
        self.assertEqual(data["file_path"], "permanent/python-async.md")

    def test_step03_save_go_note(self):
        """保存 Go 笔记，验证 auto-wikilink 自动链接 'Python Async'。"""
        result = asyncio.run(handle_save({
            "title": "Go Concurrency",
            "content": "goroutine and channel are the core of Go concurrency.\n\nPython Async also provides coroutine support.",
            "tags": ["go", "concurrency", "goroutine"],
            "type": "concept",
            "project": "backend-tools",
        }))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["action"], "created")
        self.assertEqual(data["file_path"], "backend-tools/architecture/go-concurrency.md")
        self.assertGreaterEqual(data["wikilinks_auto_suggested"], 1)

    def test_step04_save_solution_note(self):
        result = asyncio.run(handle_save({
            "title": "DB Connection Pool",
            "content": "Use HikariCP instead of DBCP.\n\nSuitable for high concurrency scenarios.",
            "tags": ["database", "java", "performance"],
            "type": "solution",
            "project": "backend-tools",
        }))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["action"], "created")
        self.assertEqual(data["file_path"], "backend-tools/features/db-connection-pool.md")

    # ── 步骤 5: vault_search ──

    def test_step05_search(self):
        """FTS5 英文搜索。"""
        result = asyncio.run(handle_search({"query": "concurrency"}))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["count"], 2)
        titles = [r["title"] for r in data["results"]]
        self.assertIn("Go Concurrency", titles)

    def test_step05b_search_with_tag_filter(self):
        result = asyncio.run(handle_search({
            "query": "hikaricp",
            "tags": ["database"],
        }))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["count"], 1)
        titles = [r["title"] for r in data["results"]]
        self.assertIn("DB Connection Pool", titles)

    # ── 步骤 6: vault_list ──

    def test_step06_list(self):
        result = asyncio.run(handle_list({}))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["count"], 3)

    def test_step06b_list_filter_by_project(self):
        result = asyncio.run(handle_list({"project": "backend-tools"}))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["count"], 2)

    # ── 步骤 7: vault_stats ──

    def test_step07_stats(self):
        result = asyncio.run(handle_stats({}))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["total_notes"], 3)
        self.assertGreaterEqual(len(data["top_tags"]), 5)

    # ── 步骤 8: vault_tags ──

    def test_step08_tags(self):
        result = asyncio.run(handle_tags({}))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["count"], 5)
        tag_names = [t["tag"] for t in data["tags"]]
        self.assertIn("python", tag_names)
        self.assertIn("go", tag_names)

    def test_step08b_tags_search(self):
        result = asyncio.run(handle_tags({"query": "concur"}))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        tag_names = [t["tag"] for t in data["tags"]]
        self.assertIn("concurrency", tag_names)

    # ── 步骤 9: vault_update ──

    def test_step09_update_append(self):
        result = asyncio.run(handle_update({
            "note_path": "permanent/python-async.md",
            "append_content": "## Reference\n- [PEP 492](https://peps.python.org/pep-0492/)",
        }))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["action"], "appended")

    def test_step09b_update_replace(self):
        result = asyncio.run(handle_update({
            "note_path": "permanent/python-async.md",
            "new_content": "# Python Async\n\nasyncio is the best choice.",
        }))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["action"], "replaced")

    # ── 步骤 10: vault_log ──

    def test_step10_log(self):
        result = asyncio.run(handle_log({
            "project": "backend-tools",
            "summary": "Completed database connection pool migration",
            "decisions": ["Use HikariCP", "Set connection timeout 30s"],
            "todos": ["Benchmark test", "Update monitoring dashboard"],
        }))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertIn("backend-tools", data["file_path"])

    # ── 步骤 11: vault_resume ──

    def test_step11_resume(self):
        result = asyncio.run(handle_resume({
            "project": "backend-tools",
            "log_count": 3,
        }))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(len(data["recent_logs"]), 1)
        log_summaries = [log.get("summary", "") for log in data["recent_logs"]]
        self.assertTrue(any("connection pool" in s.lower() for s in log_summaries))

    # ── 步骤 12: vault_orphan ──

    def test_step12_orphan(self):
        result = asyncio.run(handle_orphan({}))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertIn("no_incoming_count", data)
        self.assertIn("no_outgoing_count", data)

    # ── 步骤 13: graphify_status ──

    def test_step13_graphify_status(self):
        result = asyncio.run(handle_graphify_status({"project": "backend-tools"}))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")

    # ── 步骤 14: 幂等性验证 ──

    def test_step14_init_idempotent(self):
        result = asyncio.run(handle_init({}))
        data = _parse(result)
        self.assertEqual(data["status"], "ok")

        result2 = asyncio.run(handle_stats({}))
        stats = _parse(result2)
        self.assertEqual(stats["total_notes"], 3)


if __name__ == "__main__":
    unittest.main()
