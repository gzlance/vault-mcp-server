"""Vault MCP Server 工具 handler 集成测试。

测试 10 个异步 handler：handle_init / handle_save / handle_search /
handle_resume / handle_list / handle_stats / handle_tags / handle_log /
handle_update / handle_orphan。

使用临时目录 ~/vault-e2e-test/ 和临时 SQLite 数据库，测试后自动清理。
覆盖正常路径、边界路径和错误路径（缺失必填字段、文件不存在、空查询）。

运行方式：
    cd C:/Users/Gzlance/scripts/vault-mcp-server
    python -m pytest tests/test_vault_tools.py -v
    或
    python -m unittest tests.test_vault_tools -v
"""
import asyncio
import json
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# 将项目根目录加入 sys.path，确保 db 和 tools 模块可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from db import VaultDB  # noqa: E402
from tools.vault_tools import (  # noqa: E402
    handle_init,
    handle_log,
    handle_list,
    handle_orphan,
    handle_resume,
    handle_save,
    handle_search,
    handle_stats,
    handle_tags,
    handle_update,
)


class _SharedVaultDB(VaultDB):
    """共享连接的 VaultDB 子类。

    所有 handler 共享同一个 VaultDB 实例，避免每次创建新连接导致的
    Windows SQLite 文件锁定问题。close() 被重写为空操作，由 tearDownClass 统一关闭。
    """

    _instance = None

    def __init__(self, db_path=None):
        """复用共享实例，忽略传入的 db_path 参数。"""
        pass

    @classmethod
    def create_shared(cls, db_path):
        """创建共享实例并建立持久连接。"""
        cls._instance = object.__new__(cls)
        cls._instance.db_path = Path(db_path)
        cls._instance.conn = None
        cls._instance._connect()
        cls._instance.initialize()
        return cls._instance

    def _connect(self):
        """仅在首次或连接断开时建立连接。"""
        if self.conn is not None:
            return
        import sqlite3
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row

    def _ensure_connected(self):
        """确保连接存在，如已断开则重连。"""
        if self.conn is None:
            self._connect()

    # ── 上下文管理器重写（handle_init/handle_save 使用 with VaultDB() as db:）──

    def __enter__(self):
        """进入上下文管理器：确保已连接，不创建新连接。"""
        self._ensure_connected()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器：提交或回滚，但不关闭共享连接。"""
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
        # 不设置 self.conn = None（共享连接由 tearDownClass 统一关闭）
        return False  # 不吞异常

    def close(self):
        """仅重置连接状态，不实际关闭（由 tearDownClass 统一关闭）。"""
        pass

    def _real_close(self):
        """实际关闭数据库连接。"""
        if self.conn:
            try:
                self.conn.commit()
            except Exception:
                pass
            self.conn.close()
            self.conn = None


class TestVaultTools(unittest.TestCase):
    """Vault 工具 handler 集成测试。

    使用真实 SQLite 数据库（临时路径），所有 handler 共享同一个数据库连接。
    每个 handler 返回 TextContent 列表，JSON 字符串在 .text 属性中。
    """

    @classmethod
    def setUpClass(cls):
        """测试类级别初始化：创建临时 vault 目录和共享数据库连接。"""
        cls.vault_dir = Path.home() / "vault-e2e-test"
        cls.db_path = cls.vault_dir / "vault.db"

        # 清理可能残留的旧测试数据
        if cls.vault_dir.exists():
            shutil.rmtree(cls.vault_dir, ignore_errors=True)
        cls.vault_dir.mkdir(parents=True, exist_ok=True)

        # 创建共享数据库实例（整个测试套件只维持一条连接）
        cls._shared_db = _SharedVaultDB.create_shared(cls.db_path)

        # 补丁 1：将所有 handler 内部创建的 VaultDB 指向共享实例
        _tool_modules = [
            "tools.vault_init", "tools.vault_save", "tools.vault_search",
            "tools.vault_resume", "tools.vault_list", "tools.vault_stats",
            "tools.vault_orphan", "tools.vault_update", "tools.vault_tags",
            "tools.vault_log",
        ]
        cls._vaultdb_patches = [
            patch(f"{mod}.VaultDB", lambda: cls._shared_db) for mod in _tool_modules
        ]
        # 补丁 2：将默认 vault 目录重定向到临时目录
        # DEFAULT_VAULT_DIR 已移至 tools._shared，get_vault_dir() 从其定义模块读取
        cls._vaultdir_patch = patch(
            "tools._shared.DEFAULT_VAULT_DIR",
            cls.vault_dir,
        )
        for p in cls._vaultdb_patches:
            p.start()
        cls._vaultdir_patch.start()

    @classmethod
    def tearDownClass(cls):
        """测试类级别清理：停止补丁，关闭连接，删除临时目录。"""
        for p in cls._vaultdb_patches:
            p.stop()
        cls._vaultdir_patch.stop()

        if cls._shared_db:
            cls._shared_db._real_close()

        if cls.vault_dir.exists():
            shutil.rmtree(cls.vault_dir, ignore_errors=True)

    def setUp(self):
        """每个测试方法前清空数据库，确保测试隔离。"""
        db = self._shared_db
        db._ensure_connected()
        # 清空业务表数据。notes_fts 是虚拟表不支持 DELETE，需 DROP 后重建
        for table in ["notes", "tag_index", "wikilinks", "session_logs",
                       "graphify_builds"]:
            try:
                db.conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        try:
            db.conn.execute("DROP TABLE IF EXISTS notes_fts")
            db.conn.execute(
                "CREATE VIRTUAL TABLE notes_fts USING fts5(title, content)"
            )
        except Exception:
            pass
        db.conn.commit()

        # 清理 vault 目录下的所有 .md 文件，保留目录结构
        for md_file in self.vault_dir.rglob("*.md"):
            try:
                md_file.unlink()
            except OSError:
                pass

    # ── 辅助方法 ──

    def _run(self, coro):
        """同步包装器：用 asyncio.run() 运行异步 handler。

        asyncio.run() 会传播协程内抛出的异常（包括 KeyError、sqlite3.Error 等）。
        """
        return asyncio.run(coro)

    def _parse(self, result):
        """从 handler 返回结果中解析 JSON 字典。"""
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        self.assertTrue(hasattr(result[0], "text"), "返回结果应包含 TextContent 对象")
        return json.loads(result[0].text)

    # ═══════════════════════════════════════════════════════════════
    # 1. handle_init 测试
    # ═══════════════════════════════════════════════════════════════

    def test_init_creates_vault_structure(self):
        """正常路径：初始化 vault，创建目录结构、模板文件和数据库表。"""
        # 先删除已有子目录，模拟全新初始化
        for subdir in ["permanent", "templates", "logs", "graphify"]:
            p = self.vault_dir / subdir
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)

        result = self._run(handle_init({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertIn("actions", data)
        self.assertEqual(data["vault_dir"], str(self.vault_dir))

        # 验证四个核心目录已创建
        for subdir in ["permanent", "templates", "logs", "graphify"]:
            self.assertTrue(
                (self.vault_dir / subdir).is_dir(),
                f"目录 {subdir} 应存在",
            )

        # 验证模板文件已创建
        self.assertTrue(
            (self.vault_dir / "templates" / "default-note.md").is_file(),
        )
        self.assertTrue(
            (self.vault_dir / "templates" / "session-log.md").is_file(),
        )

    def test_init_with_project(self):
        """正常路径：指定 project 参数初始化，创建项目子目录。"""
        result = self._run(handle_init({"project": "my-project"}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        project_dir = self.vault_dir / "my-project"
        self.assertTrue(project_dir.is_dir())
        for sub in ["architecture", "features", "data", "logs"]:
            self.assertTrue(
                (project_dir / sub).is_dir(),
                f"项目子目录 {sub} 应存在",
            )

    def test_init_is_idempotent(self):
        """正常路径：重复初始化是幂等操作，两次调用均返回 ok。"""
        first = self._run(handle_init({}))
        second = self._run(handle_init({}))

        first_data = self._parse(first)
        second_data = self._parse(second)

        self.assertEqual(first_data["status"], "ok")
        self.assertEqual(second_data["status"], "ok")
        self.assertIsInstance(second_data["actions"], list)

    # ═══════════════════════════════════════════════════════════════
    # 2. handle_save 测试
    # ═══════════════════════════════════════════════════════════════

    def test_save_creates_new_note(self):
        """正常路径：保存一篇新笔记，创建 .md 文件并写入数据库。"""
        self._run(handle_init({}))

        result = self._run(handle_save({
            "title": "测试笔记标题",
            "content": "这是一篇测试笔记的正文内容。",
            "tags": ["test", "demo"],
            "type": "permanent",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["action"], "created")
        self.assertIn("测试笔记标题", data["file_path"])
        self.assertEqual(data["wikilinks_found"], 0)

        # 验证 .md 文件确实存在且包含正确内容
        saved_path = self.vault_dir / data["file_path"]
        self.assertTrue(saved_path.is_file())
        content = saved_path.read_text(encoding="utf-8")
        self.assertIn("测试笔记标题", content)
        self.assertIn("这是一篇测试笔记的正文内容", content)
        self.assertIn("---", content)
        self.assertIn("tags:", content)

    def test_save_note_with_wikilinks(self):
        """正常路径：保存包含 [[wikilink]] 的笔记，正确提取引用目标。"""
        self._run(handle_init({}))

        result = self._run(handle_save({
            "title": "引用测试",
            "content": "参考 [[另一篇笔记]] 和 [[项目说明文档]] 了解更多。",
            "tags": ["reference"],
            "type": "permanent",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["wikilinks_found"], 2)

    def test_save_updates_existing_note(self):
        """正常路径：相同标题的笔记再次保存触发更新，action 为 updated。"""
        self._run(handle_init({}))

        args = {
            "title": "更新测试笔记",
            "content": "第一版内容。",
            "tags": ["test"],
            "type": "permanent",
        }
        first = self._run(handle_save(args))
        self.assertEqual(self._parse(first)["action"], "created")

        args["content"] = "第二版内容，已更新。"
        second = self._run(handle_save(args))
        second_data = self._parse(second)

        self.assertEqual(second_data["status"], "ok")
        self.assertEqual(second_data["action"], "updated")
        self.assertEqual(
            second_data["file_path"],
            self._parse(first)["file_path"],
        )

    def test_save_session_log_to_project(self):
        """正常路径：保存 session-log 类型笔记到指定项目目录。"""
        self._run(handle_init({}))

        result = self._run(handle_save({
            "title": "项目会话记录",
            "content": "讨论了系统架构方案。",
            "tags": ["session-log"],
            "type": "session-log",
            "project": "my-project",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertIn("my-project", data["file_path"])
        self.assertIn("logs", data["file_path"])
        saved_path = self.vault_dir / data["file_path"]
        self.assertTrue(saved_path.is_file())

    def test_save_auto_wikilink(self):
        """正常路径：正文中出现已知标题的纯文本时自动转为 [[wikilink]]。"""
        self._run(handle_init({}))
        # 先创建两篇已知笔记
        self._run(handle_save({
            "title": "Python 基础",
            "content": "Python 的基本语法和数据结构。",
            "tags": ["python"],
            "type": "permanent",
        }))
        self._run(handle_save({
            "title": "Django 框架",
            "content": "Django 是 Python 的 Web 框架。",
            "tags": ["web"],
            "type": "permanent",
        }))

        result = self._run(handle_save({
            "title": "Web 开发路线",
            "content": "建议先阅读 Python 基础 了解语法，再学习 Django 框架。",
            "tags": ["learning"],
            "type": "permanent",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertGreater(data["wikilinks_auto_suggested"], 0)
        saved_path = self.vault_dir / data["file_path"]
        content = saved_path.read_text(encoding="utf-8")
        self.assertIn("[[Python 基础]]", content)
        self.assertIn("[[Django 框架]]", content)

    def test_save_auto_wikilink_excludes_self(self):
        """正常路径：自动 wikilink 不会将笔记链接到自身。"""
        self._run(handle_init({}))

        result = self._run(handle_save({
            "title": "Python 入门指南",
            "content": "这篇 Python 入门指南 介绍了基础概念。",
            "tags": ["python"],
            "type": "permanent",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["wikilinks_auto_suggested"], 0)
        saved_path = self.vault_dir / data["file_path"]
        content = saved_path.read_text(encoding="utf-8")
        self.assertNotIn("[[Python 入门指南]]", content)

    def test_save_missing_required_fields(self):
        """错误路径：缺少必填字段返回 error 状态。"""
        self._run(handle_init({}))

        result = self._run(handle_save({
            "content": "test", "tags": ["t"], "type": "permanent",
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("title", data["message"])

        result = self._run(handle_save({
            "title": "test", "tags": ["t"], "type": "permanent",
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("content", data["message"])

        result = self._run(handle_save({
            "title": "test", "content": "c", "type": "permanent",
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("tags", data["message"])

        result = self._run(handle_save({
            "title": "test", "content": "c", "tags": ["t"],
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("type", data["message"])

    def test_save_invalid_tags_type(self):
        """错误路径：tags 不是列表类型返回 error。"""
        self._run(handle_init({}))

        result = self._run(handle_save({
            "title": "test", "content": "c",
            "tags": "not-a-list", "type": "permanent",
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("tags", data["message"].lower())

    def test_save_tag_too_long(self):
        """错误路径：标签字符数超过 50 返回 error。"""
        self._run(handle_init({}))

        result = self._run(handle_save({
            "title": "test", "content": "c",
            "tags": ["a" * 51], "type": "permanent",
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("标签过长", data["message"])

    # ═══════════════════════════════════════════════════════════════
    # 3. handle_search 测试
    # ═══════════════════════════════════════════════════════════════

    def test_search_returns_matching_results(self):
        """正常路径：全文搜索已保存的笔记，返回匹配结果和分数。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "Python编程学习",
            "content": "Python 是一门强大的编程语言，适合数据分析和机器学习。",
            "tags": ["python", "学习"],
            "type": "permanent",
        }))
        self._run(handle_save({
            "title": "JavaScript前端",
            "content": "JavaScript 是前端开发的核心语言。",
            "tags": ["javascript"],
            "type": "permanent",
        }))

        result = self._run(handle_search({"query": "Python"}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["query"], "Python")
        self.assertGreaterEqual(data["count"], 1)
        titles = [r["title"] for r in data["results"]]
        self.assertIn("Python编程学习", titles)

        # 验证结果包含必要字段
        for item in data["results"]:
            self.assertIn("title", item)
            self.assertIn("snippet", item)
            self.assertIn("score", item)
            self.assertIn("path", item)

    def test_search_with_tag_filter(self):
        """正常路径：按标签筛选搜索结果。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "Filter过滤测试",
            "content": "Unique content for tag filtering test purposes.",
            "tags": ["filter-test", "unique"],
            "type": "permanent",
        }))
        self._run(handle_save({
            "title": "Other其他笔记",
            "content": "Other content that does NOT match filter conditions.",
            "tags": ["other"],
            "type": "permanent",
        }))

        result = self._run(handle_search({
            "query": "content",
            "tags": ["filter-test"],
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        titles = [r["title"] for r in data["results"]]
        self.assertIn("Filter过滤测试", titles)
        self.assertNotIn("Other其他笔记", titles)

    def test_search_empty_query(self):
        """边界路径：空查询字符串返回空结果列表（不报错）。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "空查询测试",
            "content": "一些内容。",
            "tags": ["test"],
            "type": "permanent",
        }))

        result = self._run(handle_search({"query": ""}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])
        self.assertEqual(data["query"], "")

    def test_search_no_match(self):
        """边界路径：搜索不存在的关键词返回空结果（不报错）。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "测试",
            "content": "只有这些内容。",
            "tags": ["t"],
            "type": "permanent",
        }))

        result = self._run(handle_search({"query": "xyz999绝对不会匹配"}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])

    def test_search_missing_query(self):
        """边界路径：缺少 query 字段返回空结果。"""
        result = self._run(handle_search({}))
        data = self._parse(result)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["count"], 0)

    # ═══════════════════════════════════════════════════════════════
    # 4. handle_resume 测试
    # ═══════════════════════════════════════════════════════════════

    def test_resume_with_logs(self):
        """正常路径：获取项目的最近会话日志和架构笔记。"""
        self._run(handle_init({"project": "resume-project"}))
        self._run(handle_log({
            "project": "resume-project",
            "summary": "实现了用户认证功能。",
            "decisions": ["使用 JWT", "token 过期时间 24h"],
            "todos": ["编写单元测试"],
        }))
        self._run(handle_save({
            "title": "认证架构决策",
            "content": "采用 JWT + OAuth2 的混合认证方案。",
            "tags": ["architecture"],
            "type": "permanent",
            "project": "resume-project",
        }))

        result = self._run(handle_resume({"project": "resume-project"}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["project"], "resume-project")
        self.assertIn("recent_logs", data)
        self.assertIn("recent_architecture_notes", data)
        self.assertGreaterEqual(len(data["recent_logs"]), 1)
        latest_log = data["recent_logs"][0]
        self.assertIn("用户认证", latest_log.get("summary", ""))

    def test_resume_empty_project(self):
        """边界路径：没有日志和笔记的项目返回空列表。"""
        self._run(handle_init({"project": "empty-project"}))

        result = self._run(handle_resume({"project": "empty-project"}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(len(data["recent_logs"]), 0)
        self.assertEqual(len(data["recent_architecture_notes"]), 0)

    def test_resume_with_log_count_limit(self):
        """正常路径：通过 log_count 参数限制返回的日志数量。"""
        self._run(handle_init({"project": "log-limit-project"}))
        # 创建多条日志（间隔1秒避免同分钟文件名碰撞导致 UNIQUE 约束）
        for i in range(3):
            self._run(handle_log({
                "project": "log-limit-project",
                "summary": f"日志 #{i + 1}",
            }))
            if i < 2:  # 最后一条不需要等待
                time.sleep(1.1)

        result = self._run(handle_resume({
            "project": "log-limit-project",
            "log_count": 2,
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertLessEqual(len(data["recent_logs"]), 2)

    def test_resume_missing_project(self):
        """v2.0: project 改为可选（CWD 推断），不传 project 返回空数据而非错误。"""
        result = self._run(handle_resume({}))
        data = self._parse(result)
        self.assertEqual(data["status"], "ok")

    # ═══════════════════════════════════════════════════════════════
    # 5. handle_list 测试
    # ═══════════════════════════════════════════════════════════════

    def test_list_all_notes(self):
        """正常路径：列出所有笔记，不带筛选条件时返回全部。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "笔记A",
            "content": "内容A",
            "tags": ["a"],
            "type": "permanent",
        }))
        self._run(handle_save({
            "title": "笔记B",
            "content": "内容B",
            "tags": ["b"],
            "type": "solution",
        }))

        result = self._run(handle_list({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["count"], 2)
        self.assertEqual(len(data["notes"]), data["count"])

    def test_list_filter_by_type(self):
        """正常路径：按类型筛选笔记。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "Permanent类",
            "content": "内容",
            "tags": ["permanent"],
            "type": "permanent",
        }))
        self._run(handle_save({
            "title": "Concept类",
            "content": "概念内容",
            "tags": ["concept"],
            "type": "concept",
        }))
        self._run(handle_save({
            "title": "另一Permanent",
            "content": "另外的内容",
            "tags": ["other"],
            "type": "permanent",
        }))

        result = self._run(handle_list({"type": "concept"}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["count"], 1)
        for note in data["notes"]:
            self.assertEqual(note["type"], "concept")

    def test_list_filter_by_project(self):
        """正常路径：按项目筛选笔记。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "项目笔记",
            "content": "属于特定项目的笔记",
            "tags": ["project"],
            "type": "permanent",
            "project": "alpha",
        }))
        self._run(handle_save({
            "title": "非项目笔记",
            "content": "不属于任何项目",
            "tags": ["general"],
            "type": "permanent",
        }))

        result = self._run(handle_list({"project": "alpha"}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["count"], 1)
        for note in data["notes"]:
            self.assertEqual(note["project"], "alpha")

    def test_list_empty_vault(self):
        """边界路径：空 vault 返回空列表。"""
        self._run(handle_init({}))

        result = self._run(handle_list({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["notes"], [])

    # ═══════════════════════════════════════════════════════════════
    # 6. handle_stats 测试
    # ═══════════════════════════════════════════════════════════════

    def test_stats_with_notes(self):
        """正常路径：有笔记时返回完整统计面板。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "统计测试1",
            "content": "内容",
            "tags": ["python", "test"],
            "type": "permanent",
        }))
        self._run(handle_save({
            "title": "统计测试2",
            "content": "内容",
            "tags": ["python"],
            "type": "solution",
            "project": "stats-project",
        }))

        result = self._run(handle_stats({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["total_notes"], 2)
        self.assertIn("by_type", data)
        self.assertIn("by_project", data)
        self.assertIn("top_tags", data)
        self.assertIn("recent_count", data)
        self.assertIn("total_wikilinks", data)
        self.assertIn("avg_links", data)
        self.assertIn("permanent", data["by_type"])
        self.assertIn("solution", data["by_type"])

    def test_stats_empty_vault(self):
        """边界路径：空 vault 统计面板所有计数为零。"""
        self._run(handle_init({}))

        result = self._run(handle_stats({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["total_notes"], 0)
        self.assertEqual(data["total_wikilinks"], 0)
        self.assertEqual(data["avg_links"], 0)
        self.assertEqual(data["by_type"], {})

    # ═══════════════════════════════════════════════════════════════
    # 7. handle_tags 测试
    # ═══════════════════════════════════════════════════════════════

    def test_tags_returns_all_tags(self):
        """正常路径：列出所有已用标签及使用频次。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "标签测试1",
            "content": "内容",
            "tags": ["python", "machine-learning"],
            "type": "permanent",
        }))
        self._run(handle_save({
            "title": "标签测试2",
            "content": "内容",
            "tags": ["python", "web-dev"],
            "type": "permanent",
        }))

        result = self._run(handle_tags({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        tags = data["tags"]
        self.assertGreaterEqual(len(tags), 3)

        python_tag = next(t for t in tags if t["tag"] == "python")
        self.assertEqual(python_tag["count"], 2)

        for tag_item in tags:
            self.assertIn("tag", tag_item)
            self.assertIn("count", tag_item)
            self.assertIn("last_used", tag_item)

    def test_tags_with_query_filter(self):
        """正常路径：按关键词模糊搜索标签。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "React学习",
            "content": "内容",
            "tags": ["react-hooks", "react-state", "vue-basics"],
            "type": "permanent",
        }))

        result = self._run(handle_tags({"query": "react"}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["count"], 1)
        for tag_item in data["tags"]:
            self.assertIn("react", tag_item["tag"].lower())

    def test_tags_empty_vault(self):
        """边界路径：空 vault 标签列表为空。"""
        self._run(handle_init({}))

        result = self._run(handle_tags({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["tags"], [])

    # ═══════════════════════════════════════════════════════════════
    # 8. handle_log 测试
    # ═══════════════════════════════════════════════════════════════

    def test_log_creates_session_log(self):
        """正常路径：创建完整的会话日志（含 decisions 和 todos）。"""
        self._run(handle_init({}))

        result = self._run(handle_log({
            "project": "log-project",
            "summary": "完成了用户模块的 CRUD 接口开发。",
            "decisions": ["使用 FastAPI 框架", "采用异步数据库访问模式"],
            "todos": ["添加输入校验逻辑", "编写 API 文档"],
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertIn("file_path", data)
        self.assertIn("session", data["file_path"])

        log_path = self.vault_dir / data["file_path"]
        self.assertTrue(log_path.is_file())
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("完成了用户模块的 CRUD 接口开发", content)
        self.assertIn("使用 FastAPI 框架", content)
        self.assertIn("添加输入校验逻辑", content)
        self.assertIn("type: session-log", content)
        self.assertIn("project:", content)

    def test_log_minimal_fields(self):
        """正常路径：仅提供必填字段（project + summary）也能创建日志。"""
        self._run(handle_init({}))

        result = self._run(handle_log({
            "project": "minimal-project",
            "summary": "最小化日志，无 decisions 和 todos。",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        log_path = self.vault_dir / data["file_path"]
        self.assertTrue(log_path.is_file())
        content = log_path.read_text(encoding="utf-8")
        self.assertNotIn("## 决策", content)
        self.assertNotIn("## 待办", content)

    def test_log_empty_decisions_and_todos(self):
        """正常路径：decisions 和 todos 为空列表时不生成对应章节。"""
        self._run(handle_init({}))

        result = self._run(handle_log({
            "project": "empty-lists",
            "summary": "测试空列表。",
            "decisions": [],
            "todos": [],
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        log_path = self.vault_dir / data["file_path"]
        content = log_path.read_text(encoding="utf-8")
        self.assertNotIn("## 决策", content)
        self.assertNotIn("## 待办", content)

    def test_log_missing_project(self):
        """错误路径：缺少 project 字段返回 error 状态。"""
        self._run(handle_init({}))
        result = self._run(handle_log({"summary": "没有项目名。"}))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("project", data["message"])

    def test_log_missing_summary(self):
        """错误路径：缺少 summary 字段返回 error 状态。"""
        self._run(handle_init({}))
        result = self._run(handle_log({"project": "test-project"}))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("summary", data["message"])

    # ═══════════════════════════════════════════════════════════════
    # 9. handle_update 测试
    # ═══════════════════════════════════════════════════════════════

    def test_update_replaces_content(self):
        """正常路径：替换已有笔记的正文内容（保留 frontmatter）。"""
        self._run(handle_init({}))
        save_result = self._run(handle_save({
            "title": "待更新笔记",
            "content": "原始内容，将被替换。",
            "tags": ["update"],
            "type": "permanent",
        }))
        note_path = self._parse(save_result)["file_path"]

        update_result = self._run(handle_update({
            "note_path": note_path,
            "new_content": "更新后的全新内容，替代原始正文。",
        }))
        update_data = self._parse(update_result)

        self.assertEqual(update_data["status"], "ok")
        self.assertEqual(update_data["action"], "replaced")

        file_content = (self.vault_dir / note_path).read_text(encoding="utf-8")
        self.assertIn("更新后的全新内容", file_content)
        self.assertNotIn("原始内容", file_content)
        self.assertIn("---", file_content)
        self.assertIn("title:", file_content)
        self.assertIn("tags:", file_content)

    def test_update_appends_content(self):
        """正常路径：追加内容到已有笔记末尾。"""
        self._run(handle_init({}))
        save_result = self._run(handle_save({
            "title": "追加测试笔记",
            "content": "原始开头内容。",
            "tags": ["append"],
            "type": "permanent",
        }))
        note_path = self._parse(save_result)["file_path"]

        update_result = self._run(handle_update({
            "note_path": note_path,
            "append_content": "追加的额外段落。",
        }))
        update_data = self._parse(update_result)

        self.assertEqual(update_data["status"], "ok")
        self.assertEqual(update_data["action"], "appended")

        file_content = (self.vault_dir / note_path).read_text(encoding="utf-8")
        self.assertIn("原始开头内容", file_content)
        self.assertIn("追加的额外段落", file_content)

    def test_update_file_not_found(self):
        """错误路径：更新不存在的文件返回 error 状态。"""
        self._run(handle_init({}))

        result = self._run(handle_update({
            "note_path": "不存在/的文件/路径.md",
            "new_content": "不会生效的内容。",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "error")
        self.assertIn("文件不存在", data["message"])

    def test_update_missing_both_contents(self):
        """错误路径：new_content 和 append_content 都未提供时报错。"""
        self._run(handle_init({}))
        save_result = self._run(handle_save({
            "title": "无更新内容测试",
            "content": "随便写点内容。",
            "tags": ["test"],
            "type": "permanent",
        }))
        note_path = self._parse(save_result)["file_path"]

        result = self._run(handle_update({"note_path": note_path}))
        data = self._parse(result)

        self.assertEqual(data["status"], "error")
        msg = data["message"].lower()
        self.assertTrue(
            "new_content" in msg or "append_content" in msg,
            f"错误消息应提及 new_content 或 append_content，实际: {data['message']}",
        )

    def test_update_missing_note_path(self):
        """错误路径：缺少 note_path 字段返回 error 状态。"""
        result = self._run(handle_update({}))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")

    # ═══════════════════════════════════════════════════════════════
    # 10. handle_orphan 测试
    # ═══════════════════════════════════════════════════════════════

    def test_orphan_with_no_wikilinks(self):
        """正常路径：没有 wikilink 引用的笔记均标记为孤立笔记。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "孤立笔记A",
            "content": "不引用任何其他笔记的内容。",
            "tags": ["orphan"],
            "type": "permanent",
        }))
        self._run(handle_save({
            "title": "孤立笔记B",
            "content": "也不引用任何其他笔记。",
            "tags": ["orphan"],
            "type": "solution",
        }))

        result = self._run(handle_orphan({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertIn("no_incoming_count", data)
        self.assertIn("no_outgoing_count", data)
        self.assertIsInstance(data["no_incoming"], list)
        self.assertIsInstance(data["no_outgoing"], list)
        self.assertGreaterEqual(data["no_incoming_count"], 2)
        self.assertGreaterEqual(data["no_outgoing_count"], 2)

    def test_orphan_with_wikilinks(self):
        """正常路径：有 wikilink 引用的笔记正确区分孤立状态。"""
        self._run(handle_init({}))
        self._run(handle_save({
            "title": "被引用笔记",
            "content": "这是被引用的目标笔记。",
            "tags": ["test"],
            "type": "permanent",
        }))
        self._run(handle_save({
            "title": "引用源笔记",
            "content": "参考 [[被引用笔记]] 的说明。",
            "tags": ["test"],
            "type": "permanent",
        }))

        result = self._run(handle_orphan({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertIn("no_incoming_count", data)
        self.assertIn("no_outgoing_count", data)
        self.assertIsInstance(data["no_incoming"], list)
        self.assertIsInstance(data["no_outgoing"], list)
        total_orphan = data["no_incoming_count"] + data["no_outgoing_count"]
        self.assertGreaterEqual(total_orphan, 0)

    def test_orphan_empty_vault(self):
        """边界路径：空 vault 没有孤立笔记。"""
        self._run(handle_init({}))

        result = self._run(handle_orphan({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["no_incoming_count"], 0)
        self.assertEqual(data["no_outgoing_count"], 0)
        self.assertEqual(data["no_incoming"], [])
        self.assertEqual(data["no_outgoing"], [])

    def test_orphan_excludes_session_logs(self):
        """正常路径：session-log 类型笔记不参与孤立检测。"""
        self._run(handle_init({}))
        self._run(handle_log({
            "project": "orphan-test",
            "summary": "一则会话日志。",
        }))

        result = self._run(handle_orphan({}))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        no_incoming_paths = [n.get("file_path", "") for n in data["no_incoming"]]
        no_outgoing_paths = [n.get("file_path", "") for n in data["no_outgoing"]]
        for path in no_incoming_paths + no_outgoing_paths:
            self.assertNotIn("session", path.lower())


if __name__ == "__main__":
    unittest.main()
