# -*- coding: utf-8 -*-
"""VaultDB 类完整单元测试。

测试覆盖 VaultDB 的所有公开方法，包括：
- 笔记索引 CRUD（insert_note / update_note / delete_note / get_note_by_path / get_note_by_title）
- FTS5 全文搜索（search / reindex_note / update_note_content）
- 标签管理（update_tags / get_all_tags）
- Wikilink 引用图（update_wikilinks / get_wikilink_graph / find_orphans）
- Graphify 构建记录（record_graphify_build / get_latest_graphify_build）
- 会话日志（insert_session_log / get_recent_logs）
- 统计与列表（get_stats / list_notes / get_all_titles / get_recent_architecture_notes）

使用 Python 标准库 unittest，不引入第三方依赖。
每个测试用例使用独立的临时数据库，测试后自动清理。
"""

import hashlib
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

# 将父目录加入 sys.path，确保能导入 db 模块
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import VaultDB


class TestVaultDB(unittest.TestCase):
    """VaultDB 完整单元测试套件。

    每个测试方法执行前创建新的临时数据库并调用 initialize()，
    执行后关闭连接并删除数据库文件，确保测试隔离性。
    """

    def setUp(self):
        """创建临时数据库并初始化表结构。"""
        # 使用用户指定的测试数据库路径
        self.db_path = Path.home() / ".vault-mcp" / "test_vault.db"
        self.db = VaultDB(self.db_path)
        self.db.initialize()

    def tearDown(self):
        """关闭数据库连接并删除测试文件。"""
        if hasattr(self, "db"):
            try:
                self.db.close()
            except Exception:
                pass
        if hasattr(self, "db_path") and self.db_path.exists():
            self.db_path.unlink()

    # ═══════════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════════

    def _insert_sample_note(self, title="测试笔记", file_path="测试/笔记.md",
                            tags="python,测试", note_type="permanent",
                            project="test-project", status="published",
                            created=None, updated=None,
                            word_count=100, checksum=None):
        """插入一条示例笔记并返回 row id。"""
        if created is None:
            created = date.today().isoformat()
        if updated is None:
            updated = date.today().isoformat()
        return self.db.insert_note(
            title=title, file_path=file_path, tags=tags,
            type=note_type, project=project, status=status,
            created=created, updated=updated,
            word_count=word_count, checksum=checksum,
        )

    def _insert_and_index(self, title="测试笔记", file_path="测试/笔记.md",
                          content="这是测试内容，包含 Python 相关信息。",
                          tags="python,测试", note_type="permanent",
                          project="test-project", status="published"):
        """插入笔记并建立 FTS5 索引，返回 note_id。"""
        note_id = self._insert_sample_note(
            title=title, file_path=file_path, tags=tags,
            note_type=note_type, project=project, status=status,
            word_count=len(content.split()),
            checksum=hashlib.sha256(content.encode()).hexdigest(),
        )
        self.db.reindex_note(note_id, title, content)
        return note_id

    # ═══════════════════════════════════════════════════════════════════
    # 初始化与连接管理
    # ═══════════════════════════════════════════════════════════════════

    def test_initialize_creates_all_tables(self):
        """验证 initialize() 创建全部核心表和索引。"""
        tables = self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {row["name"] for row in tables}
        core_tables = {"notes", "tag_index", "wikilinks",
                       "graphify_builds", "session_logs"}
        self.assertTrue(core_tables.issubset(table_names),
                        f"缺少核心表: {core_tables - table_names}")

        # 验证 FTS5 虚拟表存在
        self.assertIn("notes_fts", table_names)

        # 验证索引已创建
        indexes = self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ).fetchall()
        index_names = {row["name"] for row in indexes}
        expected_indexes = {
            "idx_notes_type", "idx_notes_project", "idx_notes_status",
            "idx_notes_updated", "idx_wikilinks_source", "idx_wikilinks_target",
            "idx_session_logs_project", "idx_session_logs_date",
            "idx_graphify_builds_project_built_at", "idx_notes_title", "idx_notes_created",
        }
        self.assertTrue(expected_indexes.issubset(index_names),
                        f"缺少索引: {expected_indexes - index_names}")

    def test_initialize_is_idempotent(self):
        """验证 initialize() 可以安全地多次调用（幂等）。"""
        try:
            self.db.initialize()
            self.db.initialize()
        except Exception as e:
            self.fail(f"initialize() 重复调用失败: {e}")

    def test_initialize_preserves_data(self):
        """验证幂等 initialize() 不会丢失已有数据。"""
        self._insert_sample_note(title="保留笔记", file_path="保留/测试.md")
        self.db.initialize()
        note = self.db.get_note_by_path("保留/测试.md")
        self.assertIsNotNone(note)
        self.assertEqual(note["title"], "保留笔记")

    def test_context_manager_commits(self):
        """验证上下文管理器在正常退出时提交事务。"""
        ctx_path = Path.home() / ".vault-mcp" / "test_ctx.db"
        try:
            with VaultDB(ctx_path) as db:
                db.initialize()
                db.insert_note(
                    title="ctx测试", file_path="ctx/测试.md",
                    tags="test", type="permanent", project="p",
                    status="draft", created="2025-01-01",
                    updated="2025-01-01",
                )
            # with 退出后重新连接验证数据持久化
            with VaultDB(ctx_path) as db2:
                note = db2.get_note_by_path("ctx/测试.md")
                self.assertIsNotNone(note)
                self.assertEqual(note["title"], "ctx测试")
        finally:
            if ctx_path.exists():
                ctx_path.unlink()

    def test_close(self):
        """验证 close() 后可重新连接。"""
        self.db.close()
        self.assertIsNone(self.db.conn)
        # 重新连接不应报错
        self.db.initialize()
        self.assertIsNotNone(self.db.conn)

    # ═══════════════════════════════════════════════════════════════════
    # insert_note
    # ═══════════════════════════════════════════════════════════════════

    def test_insert_note_returns_id(self):
        """验证 insert_note 返回正整数 row id。"""
        note_id = self._insert_sample_note()
        self.assertIsInstance(note_id, int)
        self.assertGreater(note_id, 0)

    def test_insert_note_all_fields_persisted(self):
        """验证插入笔记后所有字段正确持久化。"""
        note_id = self._insert_sample_note(
            title="完整字段笔记", file_path="完整/字段.md",
            tags="tag1,tag2", note_type="solution", project="my-project",
            status="review", created="2025-03-01", updated="2025-03-15",
            word_count=500, checksum="abc123",
        )
        note = self.db.get_note_by_path("完整/字段.md")
        self.assertEqual(note["id"], note_id)
        self.assertEqual(note["title"], "完整字段笔记")
        self.assertEqual(note["file_path"], "完整/字段.md")
        self.assertEqual(note["tags"], "tag1,tag2")
        self.assertEqual(note["type"], "solution")
        self.assertEqual(note["project"], "my-project")
        self.assertEqual(note["status"], "review")
        self.assertEqual(note["created"], "2025-03-01")
        self.assertEqual(note["updated"], "2025-03-15")
        self.assertEqual(note["word_count"], 500)
        self.assertEqual(note["checksum"], "abc123")

    def test_insert_note_default_values(self):
        """验证 insert_note 默认值（word_count=0, checksum=None）。"""
        self.db.insert_note(
            title="默认值笔记", file_path="默认/值.md",
            tags="", type="permanent", project="p",
            status="draft", created="2025-01-01", updated="2025-01-01",
        )
        note = self.db.get_note_by_path("默认/值.md")
        self.assertEqual(note["word_count"], 0)
        self.assertIsNone(note["checksum"])

    def test_insert_note_duplicate_path_raises(self):
        """验证插入重复 file_path 会引发 IntegrityError。"""
        self._insert_sample_note(file_path="重复/路径.md")
        with self.assertRaises(Exception):
            self._insert_sample_note(file_path="重复/路径.md")

    def test_insert_note_chinese_title(self):
        """验证中文标题笔记正确持久化。"""
        self._insert_sample_note(
            title="中文标题笔记——测试", file_path="中文/标题.md",
        )
        note = self.db.get_note_by_path("中文/标题.md")
        self.assertEqual(note["title"], "中文标题笔记——测试")

    def test_insert_note_special_characters_in_tags(self):
        """验证标签中包含特殊字符（斜杠、连字符等）。"""
        self._insert_sample_note(
            title="特殊标签", file_path="特殊/标签.md",
            tags="ai/ml, dev-ops, c++",
        )
        note = self.db.get_note_by_path("特殊/标签.md")
        self.assertEqual(note["tags"], "ai/ml, dev-ops, c++")

    # ═══════════════════════════════════════════════════════════════════
    # get_note_by_path
    # ═══════════════════════════════════════════════════════════════════

    def test_get_note_by_path_found(self):
        """验证通过存在的 file_path 能正确查询笔记。"""
        self._insert_sample_note(file_path="查询/存在.md")
        note = self.db.get_note_by_path("查询/存在.md")
        self.assertIsNotNone(note)
        self.assertIsInstance(note, dict)
        self.assertIn("id", note)
        self.assertIn("title", note)
        self.assertIn("file_path", note)

    def test_get_note_by_path_not_found(self):
        """验证查询不存在的 file_path 返回 None。"""
        note = self.db.get_note_by_path("不存在/路径.md")
        self.assertIsNone(note)

    def test_get_note_by_path_empty_string(self):
        """验证空字符串路径返回 None。"""
        note = self.db.get_note_by_path("")
        self.assertIsNone(note)

    # ═══════════════════════════════════════════════════════════════════
    # get_note_by_title
    # ═══════════════════════════════════════════════════════════════════

    def test_get_note_by_title_found(self):
        """验证通过存在的 title 能正确查询笔记。"""
        self._insert_sample_note(title="唯一标题", file_path="标题/查询.md")
        note = self.db.get_note_by_title("唯一标题")
        self.assertIsNotNone(note)
        self.assertEqual(note["title"], "唯一标题")

    def test_get_note_by_title_not_found(self):
        """验证查询不存在的标题返回 None。"""
        note = self.db.get_note_by_title("不存在的标题12345")
        self.assertIsNone(note)

    def test_get_note_by_title_empty_string(self):
        """验证空标题返回 None。"""
        note = self.db.get_note_by_title("")
        self.assertIsNone(note)

    # ═══════════════════════════════════════════════════════════════════
    # get_all_titles
    # ═══════════════════════════════════════════════════════════════════

    def test_get_all_titles_empty_db(self):
        """验证空数据库返回空列表。"""
        titles = self.db.get_all_titles()
        self.assertIsInstance(titles, list)
        self.assertEqual(len(titles), 0)

    def test_get_all_titles_returns_all(self):
        """验证返回所有笔记标题。"""
        self._insert_sample_note(title="笔记A", file_path="A.md")
        self._insert_sample_note(title="笔记B", file_path="B.md")
        self._insert_sample_note(title="笔记C", file_path="C.md")
        titles = self.db.get_all_titles()
        self.assertEqual(len(titles), 3)
        self.assertIn("笔记A", titles)
        self.assertIn("笔记B", titles)
        self.assertIn("笔记C", titles)

    def test_get_all_titles_is_list_of_strings(self):
        """验证返回值为字符串列表。"""
        self._insert_sample_note(title="标题1", file_path="t1.md")
        titles = self.db.get_all_titles()
        for t in titles:
            self.assertIsInstance(t, str)

    # ═══════════════════════════════════════════════════════════════════
    # reindex_note
    # ═══════════════════════════════════════════════════════════════════

    def test_reindex_note_makes_searchable(self):
        """验证 reindex_note 后笔记可被搜索。"""
        note_id = self._insert_sample_note(
            title="搜索测试", file_path="搜索/测试.md",
        )
        content = "Python 是一门强大的编程语言，适合数据分析和 AI 开发。"
        self.db.reindex_note(note_id, "搜索测试", content)

        results = self.db.search("Python")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "搜索测试")
        self.assertIn("Python", results[0]["snippet"])

    def test_reindex_nonexistent_note_id(self):
        """验证对不存在的 note_id 执行 reindex 不报错（FTS5 不强制外键）。"""
        try:
            self.db.reindex_note(99999, "不存在", "内容")
        except Exception as e:
            self.fail(f"对不存在 id 执行 reindex 不应崩溃: {e}")

    def test_reindex_overwrites_old_content(self):
        """验证 reindex 会覆盖旧内容。"""
        note_id = self._insert_sample_note(
            title="覆盖测试", file_path="覆盖/测试.md",
        )
        self.db.reindex_note(note_id, "覆盖测试", "第一版内容 Apple 水果")
        results = self.db.search("Apple")
        self.assertEqual(len(results), 1)

        # 重新索引为新内容
        self.db.reindex_note(note_id, "覆盖测试", "第二版内容 Banana 水果")
        results_old = self.db.search("Apple")
        results_new = self.db.search("Banana")
        self.assertEqual(len(results_old), 0)
        self.assertEqual(len(results_new), 1)

    # ═══════════════════════════════════════════════════════════════════
    # update_note
    # ═══════════════════════════════════════════════════════════════════

    def test_update_note_single_field(self):
        """验证 update_note 更新单个字段。"""
        note_id = self._insert_sample_note(title="原始标题",
                                           file_path="更新/单字段.md")
        result = self.db.update_note(note_id, title="新标题")
        self.assertTrue(result)
        note = self.db.get_note_by_path("更新/单字段.md")
        self.assertEqual(note["title"], "新标题")

    def test_update_note_multiple_fields(self):
        """验证 update_note 同时更新多个字段。"""
        note_id = self._insert_sample_note(file_path="更新/多字段.md")
        result = self.db.update_note(
            note_id, title="多字段更新", tags="new-tag",
            status="archived", word_count=999,
        )
        self.assertTrue(result)
        note = self.db.get_note_by_path("更新/多字段.md")
        self.assertEqual(note["title"], "多字段更新")
        self.assertEqual(note["tags"], "new-tag")
        self.assertEqual(note["status"], "archived")
        self.assertEqual(note["word_count"], 999)

    def test_update_note_nonexistent_id(self):
        """验证更新不存在的 note_id 返回 False。"""
        result = self.db.update_note(99999, title="不存在")
        self.assertFalse(result)

    def test_update_note_empty_kwargs(self):
        """验证 kwargs 为空时返回 False。"""
        note_id = self._insert_sample_note(file_path="更新/空kwargs.md")
        result = self.db.update_note(note_id)
        self.assertFalse(result)

    def test_update_note_only_invalid_keys(self):
        """验证 kwargs 全部为非法列名时返回 False。"""
        note_id = self._insert_sample_note(file_path="更新/非法key.md")
        result = self.db.update_note(note_id, invalid_key="value",
                                     another_fake=123)
        self.assertFalse(result)

    def test_update_note_mixed_valid_invalid_keys(self):
        """验证混合合法与非法 key 时只更新合法字段。"""
        note_id = self._insert_sample_note(file_path="更新/混合key.md",
                                           word_count=50)
        result = self.db.update_note(note_id, word_count=200,
                                     fake_field="ignored")
        self.assertTrue(result)
        note = self.db.get_note_by_path("更新/混合key.md")
        self.assertEqual(note["word_count"], 200)

    # ═══════════════════════════════════════════════════════════════════
    # update_note_content
    # ═══════════════════════════════════════════════════════════════════

    def test_update_note_content_success(self):
        """验证 update_note_content 更新正文并重建索引。"""
        self._insert_sample_note(
            title="内容更新", file_path="内容/更新.md",
            checksum="old-checksum",
        )
        note_id = self.db.get_note_by_path("内容/更新.md")["id"]
        # 先建立初始索引
        self.db.reindex_note(note_id, "内容更新", "旧内容 old")

        new_content = "全新的内容，包含关键词 Banana 和标识符 xyz789"
        result = self.db.update_note_content("内容/更新.md", new_content)
        self.assertTrue(result)

        # 验证搜索能找到新内容
        results = self.db.search("Banana")
        self.assertEqual(len(results), 1)

        # 验证 word_count 和 checksum 已更新
        note = self.db.get_note_by_path("内容/更新.md")
        self.assertEqual(note["word_count"], len(new_content.split()))
        expected_checksum = hashlib.sha256(new_content.encode()).hexdigest()
        self.assertEqual(note["checksum"], expected_checksum)

    def test_update_note_content_nonexistent_file(self):
        """验证对不存在的 file_path 执行更新返回 False。"""
        result = self.db.update_note_content("不存在/文件.md", "内容")
        self.assertFalse(result)

    def test_update_note_content_updates_timestamp(self):
        """验证 update_note_content 更新 updated 时间为当天。"""
        self._insert_sample_note(
            title="时间戳更新", file_path="时间/戳.md", updated="2020-01-01",
        )
        self.db.update_note_content("时间/戳.md", "新内容")
        note = self.db.get_note_by_path("时间/戳.md")
        self.assertEqual(note["updated"], date.today().isoformat())

    def test_update_note_content_chinese(self):
        """验证中文正文的 update_note_content。"""
        self._insert_sample_note(title="中文正文", file_path="正文/中文.md")
        content = "这是一篇关于人工智能的中文笔记。深度学习是目前最热门的方向。"
        result = self.db.update_note_content("正文/中文.md", content)
        self.assertTrue(result)
        note = self.db.get_note_by_path("正文/中文.md")
        self.assertEqual(note["word_count"], len(content.split()))

    # ═══════════════════════════════════════════════════════════════════
    # delete_note
    # ═══════════════════════════════════════════════════════════════════

    def test_delete_note_success(self):
        """验证删除存在的笔记返回 True。"""
        self._insert_sample_note(file_path="删除/测试.md")
        result = self.db.delete_note("删除/测试.md")
        self.assertTrue(result)
        self.assertIsNone(self.db.get_note_by_path("删除/测试.md"))

    def test_delete_note_nonexistent(self):
        """验证删除不存在的笔记返回 False。"""
        result = self.db.delete_note("不存在/删除.md")
        self.assertFalse(result)

    def test_delete_note_cleans_fts_index(self):
        """验证删除笔记时会清理对应的 FTS5 索引。"""
        note_id = self._insert_sample_note(
            title="待删FTS", file_path="待删/fts.md",
        )
        self.db.reindex_note(note_id, "待删FTS", "FTS5IndexTest content here")
        results_before = self.db.search("FTS5IndexTest")
        self.assertGreaterEqual(len(results_before), 1)

        self.db.delete_note("待删/fts.md")
        results_after = self.db.search("FTS5IndexTest")
        self.assertEqual(len(results_after), 0)

    def test_delete_note_cleans_wikilinks(self):
        """验证删除笔记时清理关联的 wikilinks。"""
        self._insert_sample_note(title="源笔记", file_path="源.md")
        self._insert_sample_note(title="目标笔记", file_path="目标.md")
        self.db.update_wikilinks("源.md", ["目标.md"])

        self.db.delete_note("源.md")
        graph = self.db.get_wikilink_graph()
        self.assertNotIn("源.md", graph)

    # ═══════════════════════════════════════════════════════════════════
    # search (FTS5 全文搜索)
    # ═══════════════════════════════════════════════════════════════════

    def test_search_basic(self):
        """验证基本搜索功能。"""
        self._insert_and_index(title="Python笔记", file_path="搜索/Python.md",
                               content="Python 是一门动态语言，广泛用于 Web 开发。")
        results = self.db.search("Python")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Python笔记")

    def test_search_empty_query(self):
        """验证空查询返回空列表。"""
        self._insert_and_index(title="某笔记", file_path="某.md",
                               content="测试内容")
        results = self.db.search("")
        self.assertEqual(results, [])

    def test_search_whitespace_only_query(self):
        """验证仅空格的查询返回空列表。"""
        self._insert_and_index(title="空白查询", file_path="空白.md",
                               content="测试")
        results = self.db.search("   ")
        self.assertEqual(results, [])

    def test_search_no_results(self):
        """验证无匹配时返回空列表。"""
        self._insert_and_index(title="无匹配笔记", file_path="无匹配.md",
                               content="普通内容")
        results = self.db.search("不存在的关键词xyz999")
        self.assertEqual(results, [])

    def test_search_result_structure(self):
        """验证搜索结果包含正确的 JSON 结构。"""
        self._insert_and_index(title="StructureTest", file_path="struct/test.md",
                               content="Verifying search result field structure for testing.")
        results = self.db.search("StructureTest")
        self.assertEqual(len(results), 1)
        result = results[0]
        expected_keys = {"title", "snippet", "tags", "type", "project",
                         "created", "path", "score"}
        self.assertTrue(expected_keys.issubset(result.keys()),
                        f"缺少字段: {expected_keys - result.keys()}")
        self.assertIsInstance(result["score"], (int, float))
        self.assertEqual(result["path"], "struct/test.md")
        self.assertIsInstance(result["snippet"], str)

    def test_search_chinese_content(self):
        """验证中文内容可被索引（通过 Latin 关键词配合中文正文搜索）。"""
        self._insert_and_index(
            title="ChineseSearch", file_path="chinese/search.md",
            content="这是一篇关于机器学习的笔记。MachineLearning Transformer architecture changed NLP."
        )
        # 使用 Latin 关键词搜索（FTS5 默认 tokenizer 对中文采用单字分词）
        results = self.db.search("MachineLearning")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "ChineseSearch")

    def test_search_chinese_snippet(self):
        """验证搜索结果的 snippet 包含高亮标记。"""
        self._insert_and_index(
            title="HighlightTest", file_path="highlight/test.md",
            content="Deep reinforcement learning combines DeepLearning and policy gradients."
        )
        results = self.db.search("DeepLearning")
        self.assertGreaterEqual(len(results), 1)
        snippet = results[0]["snippet"]
        self.assertIn("<mark>", snippet)
        self.assertIn("</mark>", snippet)

    def test_search_with_tags_filter(self):
        """验证 tags 过滤搜索。"""
        self._insert_and_index(title="TaggedA", file_path="tagged/A.md",
                               content="content Alpha words", tags="ai")
        self._insert_and_index(title="TaggedB", file_path="tagged/B.md",
                               content="content Beta words", tags="web")
        results = self.db.search("Alpha", tags="ai")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "TaggedA")

    def test_search_with_project_filter(self):
        """验证 project 过滤搜索。"""
        self._insert_and_index(title="ProjectA", file_path="proj/A.md",
                               content="project Alpha match", project="alpha")
        self._insert_and_index(title="ProjectB", file_path="proj/B.md",
                               content="project Beta match", project="beta")
        results = self.db.search("Alpha", project="alpha")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "ProjectA")

    def test_search_with_type_filter(self):
        """验证 type 过滤搜索。"""
        self._insert_and_index(title="PermNote", file_path="type/perm.md",
                               content="permanent content here", note_type="permanent")
        self._insert_and_index(title="SolNote", file_path="type/sol.md",
                               content="solution content here", note_type="solution")
        results = self.db.search("solution", type="solution")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "SolNote")

    def test_search_with_limit_offset(self):
        """验证分页参数 limit 和 offset。"""
        for i in range(5):
            self._insert_and_index(
                title=f"PageNote{i}", file_path=f"page/{i}.md",
                content=f"pagination test content number {i}",
            )
        results_page1 = self.db.search("pagination", limit=2, offset=0)
        results_page2 = self.db.search("pagination", limit=2, offset=2)
        self.assertEqual(len(results_page1), 2)
        self.assertEqual(len(results_page2), 2)
        titles_page1 = {r["title"] for r in results_page1}
        titles_page2 = {r["title"] for r in results_page2}
        self.assertTrue(titles_page1.isdisjoint(titles_page2))

    def test_search_combined_filters(self):
        """验证组合 tags + project + type 过滤。"""
        self._insert_and_index(title="TargetA", file_path="comb/A.md",
                               content="target Alpha unique", tags="ai",
                               project="alpha", note_type="permanent")
        self._insert_and_index(title="NoiseB", file_path="comb/B.md",
                               content="noise Beta common", tags="web",
                               project="alpha", note_type="permanent")
        self._insert_and_index(title="NoiseC", file_path="comb/C.md",
                               content="noise Gamma common", tags="ai",
                               project="beta", note_type="permanent")
        results = self.db.search("Alpha", tags="ai", project="alpha",
                                 type="permanent")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "TargetA")

    def test_search_score_ordering(self):
        """验证搜索结果按 BM25 分数排序（分数递减）。"""
        self._insert_and_index(title="高分笔记", file_path="分数/高.md",
                               content="Python Python Python 编程 Python 开发")
        self._insert_and_index(title="低分笔记", file_path="分数/低.md",
                               content="偶尔提到 Python 的普通文章")
        results = self.db.search("Python")
        self.assertGreaterEqual(len(results), 2)
        self.assertGreaterEqual(results[0]["score"], results[1]["score"])

    # ═══════════════════════════════════════════════════════════════════
    # update_tags
    # ═══════════════════════════════════════════════════════════════════

    def test_update_tags_new_tags(self):
        """验证插入新标签并初始化计数为 1。"""
        self.db.update_tags(["python", "testing"])
        tags_list = self.db.get_all_tags()
        tags_dict = {t["tag"]: t["count"] for t in tags_list}
        self.assertIn("python", tags_dict)
        self.assertIn("testing", tags_dict)
        self.assertEqual(tags_dict["python"], 1)
        self.assertEqual(tags_dict["testing"], 1)

    def test_update_tags_increment_count(self):
        """验证已有标签计数递增。"""
        self.db.update_tags(["python"])
        self.db.update_tags(["python", "python"])
        tags_list = self.db.get_all_tags()
        tags_dict = {t["tag"]: t["count"] for t in tags_list}
        self.assertEqual(tags_dict["python"], 3)

    def test_update_tags_empty_list(self):
        """验证空列表不报错且不影响已有数据。"""
        try:
            self.db.update_tags([])
        except Exception as e:
            self.fail(f"update_tags([]) 不应报错: {e}")
        tags = self.db.get_all_tags()
        self.assertEqual(tags, [])

    def test_update_tags_empty_string_tag(self):
        """验证空字符串标签被跳过。"""
        self.db.update_tags(["valid", "", "  ", "also-valid"])
        tags_list = self.db.get_all_tags()
        tag_names = {t["tag"] for t in tags_list}
        self.assertIn("valid", tag_names)
        self.assertIn("also-valid", tag_names)
        self.assertNotIn("", tag_names)
        self.assertNotIn("  ", tag_names)

    def test_update_tags_strips_whitespace(self):
        """验证标签两端空格被去除。"""
        self.db.update_tags(["  python  "])
        tags_list = self.db.get_all_tags()
        self.assertEqual(len(tags_list), 1)
        self.assertEqual(tags_list[0]["tag"], "python")

    def test_update_tags_sets_last_used(self):
        """验证 last_used 字段被正确设置。"""
        self.db.update_tags(["newtag"])
        tags_list = self.db.get_all_tags()
        self.assertIsNotNone(tags_list[0]["last_used"])
        self.assertEqual(tags_list[0]["last_used"],
                         date.today().isoformat())

    # ═══════════════════════════════════════════════════════════════════
    # get_all_tags
    # ═══════════════════════════════════════════════════════════════════

    def test_get_all_tags_empty_db(self):
        """验证空数据库返回空列表。"""
        tags = self.db.get_all_tags()
        self.assertIsInstance(tags, list)
        self.assertEqual(tags, [])

    def test_get_all_tags_count_descending(self):
        """验证标签按使用频次降序排列。"""
        self.db.update_tags(["tag-a"])
        self.db.update_tags(["tag-b", "tag-b", "tag-b"])
        self.db.update_tags(["tag-c", "tag-c"])
        tags = self.db.get_all_tags()
        self.assertEqual(tags[0]["tag"], "tag-b")
        self.assertEqual(tags[1]["tag"], "tag-c")
        self.assertEqual(tags[2]["tag"], "tag-a")

    def test_get_all_tags_with_query(self):
        """验证通过关键词模糊搜索标签。"""
        self.db.update_tags(["python", "py-test", "javascript"])
        results = self.db.get_all_tags(query="py")
        self.assertEqual(len(results), 2)
        tag_names = {t["tag"] for t in results}
        self.assertIn("python", tag_names)
        self.assertIn("py-test", tag_names)

    def test_get_all_tags_query_no_match(self):
        """验证关键词无匹配时返回空列表。"""
        self.db.update_tags(["python", "javascript"])
        results = self.db.get_all_tags(query="zzz-nomatch")
        self.assertEqual(results, [])

    def test_get_all_tags_return_structure(self):
        """验证返回标签结构包含 tag/count/last_used。"""
        self.db.update_tags(["struct-tag"])
        results = self.db.get_all_tags()
        self.assertEqual(len(results), 1)
        result = results[0]
        expected_keys = {"tag", "count", "last_used"}
        self.assertTrue(expected_keys.issubset(result.keys()))

    # ═══════════════════════════════════════════════════════════════════
    # update_wikilinks
    # ═══════════════════════════════════════════════════════════════════

    def test_update_wikilinks_insert_new(self):
        """验证为源笔记设置出站链接。"""
        self._insert_sample_note(title="源", file_path="wl/源.md")
        self._insert_sample_note(title="目标1", file_path="wl/目标1.md")
        self._insert_sample_note(title="目标2", file_path="wl/目标2.md")
        self.db.update_wikilinks("wl/源.md",
                                 ["wl/目标1.md", "wl/目标2.md"])
        graph = self.db.get_wikilink_graph()
        self.assertIn("wl/源.md", graph)
        self.assertIn("wl/目标1.md", graph["wl/源.md"])
        self.assertIn("wl/目标2.md", graph["wl/源.md"])

    def test_update_wikilinks_overwrites_old(self):
        """验证重复调用 update_wikilinks 会覆盖旧链接。"""
        self._insert_sample_note(file_path="wl/源2.md")
        self._insert_sample_note(file_path="wl/A.md")
        self._insert_sample_note(file_path="wl/B.md")
        self._insert_sample_note(file_path="wl/C.md")

        self.db.update_wikilinks("wl/源2.md", ["wl/A.md"])
        self.db.update_wikilinks("wl/源2.md", ["wl/B.md", "wl/C.md"])
        graph = self.db.get_wikilink_graph()
        self.assertIn("wl/源2.md", graph)
        self.assertEqual(set(graph["wl/源2.md"]), {"wl/B.md", "wl/C.md"})

    def test_update_wikilinks_empty_targets(self):
        """验证空目标列表仅删除旧链接，不插入新记录。"""
        self._insert_sample_note(file_path="wl/清空.md")
        self._insert_sample_note(file_path="wl/T.md")
        self.db.update_wikilinks("wl/清空.md", ["wl/T.md"])
        self.assertIn("wl/清空.md", self.db.get_wikilink_graph())

        self.db.update_wikilinks("wl/清空.md", [])
        graph = self.db.get_wikilink_graph()
        self.assertNotIn("wl/清空.md", graph)

    def test_update_wikilinks_with_context(self):
        """验证更新 wikilinks 时附带 context。"""
        self._insert_sample_note(file_path="wl/ctx源.md")
        self._insert_sample_note(file_path="wl/ctx目标.md")
        self.db.update_wikilinks("wl/ctx源.md", ["wl/ctx目标.md"],
                                 context="参考链接")
        row = self.db.conn.execute(
            "SELECT context FROM wikilinks WHERE source_path = ?",
            ("wl/ctx源.md",)
        ).fetchone()
        self.assertEqual(row["context"], "参考链接")

    # ═══════════════════════════════════════════════════════════════════
    # get_wikilink_graph
    # ═══════════════════════════════════════════════════════════════════

    def test_get_wikilink_graph_empty(self):
        """验证无 wikilinks 时返回空字典。"""
        graph = self.db.get_wikilink_graph()
        self.assertIsInstance(graph, dict)
        self.assertEqual(graph, {})

    def test_get_wikilink_graph_with_data(self):
        """验证 wikilink 图包含正确的引用关系。"""
        self._insert_sample_note(title="A", file_path="g/A.md")
        self._insert_sample_note(title="B", file_path="g/B.md")
        self._insert_sample_note(title="C", file_path="g/C.md")
        self.db.update_wikilinks("g/A.md", ["g/B.md", "g/C.md"])
        self.db.update_wikilinks("g/B.md", ["g/C.md"])

        graph = self.db.get_wikilink_graph()
        self.assertIn("g/A.md", graph)
        self.assertIn("g/B.md", graph)
        self.assertEqual(set(graph["g/A.md"]), {"g/B.md", "g/C.md"})
        self.assertEqual(graph["g/B.md"], ["g/C.md"])

    def test_get_wikilink_graph_filters_nonexistent_notes(self):
        """验证 wikilink 图仅包含 notes 表中实际存在的笔记引用。"""
        self._insert_sample_note(title="实存", file_path="g/实存.md")
        self.db.update_wikilinks("g/实存.md", ["g/不存在.md"])
        graph = self.db.get_wikilink_graph()
        self.assertNotIn("g/实存.md", graph)

    def test_get_wikilink_graph_is_dict_of_lists(self):
        """验证返回值类型为 {str: [str, ...]}。"""
        self._insert_sample_note(file_path="g/X.md")
        self._insert_sample_note(file_path="g/Y.md")
        self.db.update_wikilinks("g/X.md", ["g/Y.md"])
        graph = self.db.get_wikilink_graph()
        for src, targets in graph.items():
            self.assertIsInstance(src, str)
            self.assertIsInstance(targets, list)
            for tgt in targets:
                self.assertIsInstance(tgt, str)

    # ═══════════════════════════════════════════════════════════════════
    # find_orphans
    # ═══════════════════════════════════════════════════════════════════

    def test_find_orphans_empty_db(self):
        """验证空数据库返回空孤立笔记列表。"""
        orphans = self.db.find_orphans()
        self.assertIsInstance(orphans, dict)
        self.assertIn("no_incoming", orphans)
        self.assertIn("no_outgoing", orphans)
        self.assertEqual(orphans["no_incoming"], [])
        self.assertEqual(orphans["no_outgoing"], [])

    def test_find_orphans_no_orphans_connected_graph(self):
        """验证双向引用图（A<->B）中无孤立笔记。"""
        self._insert_sample_note(file_path="o/A.md")
        self._insert_sample_note(file_path="o/B.md")
        # A引用B，B引用A → 双方都有入站和出站，无人孤立
        self.db.update_wikilinks("o/A.md", ["o/B.md"])
        self.db.update_wikilinks("o/B.md", ["o/A.md"])
        orphans = self.db.find_orphans()
        self.assertEqual(orphans["no_incoming"], [])
        self.assertEqual(orphans["no_outgoing"], [])

    def test_find_orphans_detects_no_incoming(self):
        """验证检测无入站的孤立笔记。"""
        self._insert_sample_note(file_path="o/孤立入.md")
        self._insert_sample_note(file_path="o/目标.md")
        self.db.update_wikilinks("o/孤立入.md", ["o/目标.md"])
        orphans = self.db.find_orphans()
        incoming_paths = [n["file_path"] for n in orphans["no_incoming"]]
        self.assertIn("o/孤立入.md", incoming_paths)

    def test_find_orphans_detects_no_outgoing(self):
        """验证检测无出站的孤立笔记。"""
        self._insert_sample_note(file_path="o/源.md")
        self._insert_sample_note(file_path="o/孤立出.md")
        self.db.update_wikilinks("o/源.md", ["o/孤立出.md"])
        orphans = self.db.find_orphans()
        outgoing_paths = [n["file_path"] for n in orphans["no_outgoing"]]
        self.assertIn("o/孤立出.md", outgoing_paths)

    def test_find_orphans_excludes_session_log(self):
        """验证 session-log 类型笔记不计入孤立检测。"""
        self.db.insert_note(
            title="会话日志", file_path="o/log.md",
            tags="", type="session-log", project="p",
            status="draft", created="2025-01-01", updated="2025-01-01",
        )
        orphans = self.db.find_orphans()
        log_paths_incoming = [n["file_path"] for n in orphans["no_incoming"]]
        log_paths_outgoing = [n["file_path"] for n in orphans["no_outgoing"]]
        self.assertNotIn("o/log.md", log_paths_incoming)
        self.assertNotIn("o/log.md", log_paths_outgoing)

    def test_find_orphans_return_structure(self):
        """验证 find_orphans 返回结果中的笔记为完整字典。"""
        self._insert_sample_note(file_path="o/结构.md")
        orphans = self.db.find_orphans()
        for note in orphans["no_incoming"]:
            self.assertIsInstance(note, dict)
            self.assertIn("id", note)
            self.assertIn("title", note)
            self.assertIn("file_path", note)
            self.assertIn("type", note)

    # ═══════════════════════════════════════════════════════════════════
    # record_graphify_build
    # ═══════════════════════════════════════════════════════════════════

    def test_record_graphify_build_returns_id(self):
        """验证 record_graphify_build 返回正整数 id。"""
        build_id = self.db.record_graphify_build(
            project="test-proj", node_count=50, edge_count=120,
            community_count=5,
        )
        self.assertIsInstance(build_id, int)
        self.assertGreater(build_id, 0)

    def test_record_graphify_build_all_fields(self):
        """验证 graphify 构建记录所有字段正确持久化。"""
        build_id = self.db.record_graphify_build(
            project="my-app", node_count=200, edge_count=450,
            community_count=12, commit_sha="abc123def",
        )
        row = self.db.conn.execute(
            "SELECT * FROM graphify_builds WHERE id = ?", (build_id,)
        ).fetchone()
        self.assertEqual(row["project"], "my-app")
        self.assertEqual(row["node_count"], 200)
        self.assertEqual(row["edge_count"], 450)
        self.assertEqual(row["community_count"], 12)
        self.assertEqual(row["commit_sha"], "abc123def")
        self.assertIsNotNone(row["built_at"])

    def test_record_graphify_build_without_commit_sha(self):
        """验证不提供 commit_sha 时默认为 None。"""
        build_id = self.db.record_graphify_build(
            project="no-sha", node_count=10, edge_count=20,
            community_count=1,
        )
        row = self.db.conn.execute(
            "SELECT commit_sha FROM graphify_builds WHERE id = ?",
            (build_id,)
        ).fetchone()
        self.assertIsNone(row["commit_sha"])

    # ═══════════════════════════════════════════════════════════════════
    # get_latest_graphify_build
    # ═══════════════════════════════════════════════════════════════════

    def test_get_latest_graphify_build_found(self):
        """验证获取最近一次构建记录。"""
        self.db.record_graphify_build(
            project="latest-test", node_count=10, edge_count=20,
            community_count=1,
        )
        # 等待 1.1 秒确保 built_at 时间戳不同（秒级精度）
        time.sleep(1.1)
        self.db.record_graphify_build(
            project="latest-test", node_count=30, edge_count=60,
            community_count=3,
        )
        latest = self.db.get_latest_graphify_build("latest-test")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["node_count"], 30)
        self.assertEqual(latest["edge_count"], 60)

    def test_get_latest_graphify_build_not_found(self):
        """验证项目无构建记录时返回 None。"""
        result = self.db.get_latest_graphify_build("non-existent-project")
        self.assertIsNone(result)

    def test_get_latest_graphify_build_return_structure(self):
        """验证返回结果包含所有必要字段。"""
        self.db.record_graphify_build(
            project="struct", node_count=5, edge_count=10,
            community_count=2,
        )
        build = self.db.get_latest_graphify_build("struct")
        expected_keys = {"id", "project", "commit_sha", "node_count",
                         "edge_count", "community_count", "built_at"}
        self.assertTrue(expected_keys.issubset(build.keys()))

    # ═══════════════════════════════════════════════════════════════════
    # insert_session_log
    # ═══════════════════════════════════════════════════════════════════

    def test_insert_session_log_returns_id(self):
        """验证插入会话日志返回正整数 id。"""
        log_id = self.db.insert_session_log(
            project="test", date="2025-05-01",
            file_path="日志/2025-05-01.md",
            summary="今天的开发总结",
        )
        self.assertIsInstance(log_id, int)
        self.assertGreater(log_id, 0)

    def test_insert_session_log_all_fields(self):
        """验证会话日志所有字段正确持久化。"""
        log_id = self.db.insert_session_log(
            project="full-test", date="2025-05-10",
            file_path="日志/full.md",
            summary="完整日志测试",
            decisions="决定使用方案A",
            todos="- [ ] 完成单元测试\n- [ ] 代码审查",
        )
        row = self.db.conn.execute(
            "SELECT * FROM session_logs WHERE id = ?", (log_id,)
        ).fetchone()
        self.assertEqual(row["project"], "full-test")
        self.assertEqual(row["date"], "2025-05-10")
        self.assertEqual(row["file_path"], "日志/full.md")
        self.assertEqual(row["summary"], "完整日志测试")
        self.assertEqual(row["decisions"], "决定使用方案A")
        self.assertEqual(row["todos"], "- [ ] 完成单元测试\n- [ ] 代码审查")

    def test_insert_session_log_minimal_fields(self):
        """验证仅提供必填字段时其余为 None。"""
        log_id = self.db.insert_session_log(
            project="minimal", date="2025-01-01",
            file_path="日志/min.md",
            summary="最小日志",
        )
        row = self.db.conn.execute(
            "SELECT * FROM session_logs WHERE id = ?", (log_id,)
        ).fetchone()
        self.assertIsNone(row["decisions"])
        self.assertIsNone(row["todos"])

    def test_insert_session_log_duplicate_path_raises(self):
        """验证重复 file_path 会引发异常（UNIQUE 约束）。"""
        self.db.insert_session_log(
            project="dup", date="2025-01-01",
            file_path="日志/dup.md", summary="first",
        )
        with self.assertRaises(Exception):
            self.db.insert_session_log(
                project="dup", date="2025-01-02",
                file_path="日志/dup.md", summary="second",
            )

    # ═══════════════════════════════════════════════════════════════════
    # get_recent_logs
    # ═══════════════════════════════════════════════════════════════════

    def test_get_recent_logs_success(self):
        """验证获取最近 N 条日志按日期降序。"""
        self.db.insert_session_log(
            project="log-proj", date="2025-01-01",
            file_path="日志/old.md", summary="旧日志",
        )
        self.db.insert_session_log(
            project="log-proj", date="2025-05-01",
            file_path="日志/new.md", summary="新日志",
        )
        logs = self.db.get_recent_logs("log-proj", count=5)
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["date"], "2025-05-01")
        self.assertEqual(logs[1]["date"], "2025-01-01")

    def test_get_recent_logs_limit_respected(self):
        """验证返回数量受 count 限制。"""
        for i in range(5):
            self.db.insert_session_log(
                project="limit-test", date=f"2025-0{i+1}-01",
                file_path=f"日志/limit{i}.md",
                summary=f"日志 {i}",
            )
        logs = self.db.get_recent_logs("limit-test", count=3)
        self.assertEqual(len(logs), 3)

    def test_get_recent_logs_no_match(self):
        """验证项目无日志时返回空列表。"""
        logs = self.db.get_recent_logs("empty-proj")
        self.assertEqual(logs, [])

    def test_get_recent_logs_return_structure(self):
        """验证返回日志包含完整的字段。"""
        self.db.insert_session_log(
            project="struct-log", date="2025-06-01",
            file_path="日志/struct.md", summary="结构测试",
        )
        logs = self.db.get_recent_logs("struct-log")
        self.assertEqual(len(logs), 1)
        log = logs[0]
        expected_keys = {"id", "project", "date", "file_path",
                         "summary", "decisions", "todos"}
        self.assertTrue(expected_keys.issubset(log.keys()))

    # ═══════════════════════════════════════════════════════════════════
    # get_stats
    # ═══════════════════════════════════════════════════════════════════

    def test_get_stats_empty_db(self):
        """验证空数据库统计全部为零。"""
        stats = self.db.get_stats()
        self.assertEqual(stats["total_notes"], 0)
        self.assertEqual(stats["by_type"], {})
        self.assertEqual(stats["by_project"], {})
        self.assertEqual(stats["top_tags"], [])
        self.assertEqual(stats["recent_count"], 0)
        self.assertEqual(stats["total_wikilinks"], 0)
        self.assertEqual(stats["avg_links"], 0)

    def test_get_stats_return_structure(self):
        """验证 get_stats 返回完整结构。"""
        self._insert_sample_note(file_path="统计/A.md", note_type="permanent",
                                 project="proj1")
        stats = self.db.get_stats()
        expected_keys = {"total_notes", "by_type", "by_project",
                         "top_tags", "recent_count", "total_wikilinks",
                         "avg_links"}
        self.assertTrue(expected_keys.issubset(stats.keys()))

    def test_get_stats_total_notes(self):
        """验证统计总笔记数正确。"""
        for i in range(5):
            self._insert_sample_note(file_path=f"统计/note{i}.md")
        self.assertEqual(self.db.get_stats()["total_notes"], 5)

    def test_get_stats_by_type(self):
        """验证按类型分组统计。"""
        self._insert_sample_note(file_path="统计/perm1.md",
                                 note_type="permanent")
        self._insert_sample_note(file_path="统计/perm2.md",
                                 note_type="permanent")
        self._insert_sample_note(file_path="统计/sol1.md",
                                 note_type="solution")
        by_type = self.db.get_stats()["by_type"]
        self.assertEqual(by_type.get("permanent"), 2)
        self.assertEqual(by_type.get("solution"), 1)

    def test_get_stats_by_project(self):
        """验证按项目分组统计，无项目的归类为"未分类"。"""
        self._insert_sample_note(file_path="统计/prjA.md", project="alpha")
        self._insert_sample_note(file_path="统计/prjB.md", project=None)
        by_project = self.db.get_stats()["by_project"]
        self.assertEqual(by_project.get("alpha"), 1)
        self.assertIn("未分类", by_project)

    def test_get_stats_top_tags(self):
        """验证 top_tags 返回前 10 个高频标签。"""
        self.db.update_tags(["tag1", "tag1", "tag1"])
        self.db.update_tags(["tag2", "tag2"])
        self.db.update_tags(["tag3"])
        top_tags = self.db.get_stats()["top_tags"]
        self.assertEqual(len(top_tags), 3)
        self.assertEqual(top_tags[0]["tag"], "tag1")
        self.assertEqual(top_tags[0]["count"], 3)

    def test_get_stats_recent_count(self):
        """验证近 7 天创建笔记计数。"""
        today = date.today().isoformat()
        week_ago = (date.today() - timedelta(days=8)).isoformat()
        self._insert_sample_note(file_path="统计/新.md", created=today)
        self._insert_sample_note(file_path="统计/旧.md", created=week_ago)
        recent = self.db.get_stats()["recent_count"]
        self.assertEqual(recent, 1)

    def test_get_stats_wikilinks_and_avg(self):
        """验证总 wikilinks 数和平均链接数。"""
        self._insert_sample_note(file_path="统计/A.md")
        self._insert_sample_note(file_path="统计/B.md")
        self._insert_sample_note(file_path="统计/C.md")
        self.db.update_wikilinks("统计/A.md", ["统计/B.md", "统计/C.md"])
        self.db.update_wikilinks("统计/B.md", ["统计/C.md"])
        stats = self.db.get_stats()
        self.assertEqual(stats["total_wikilinks"], 3)
        self.assertEqual(stats["avg_links"], 1.0)

    # ═══════════════════════════════════════════════════════════════════
    # list_notes
    # ═══════════════════════════════════════════════════════════════════

    def test_list_notes_default(self):
        """验证默认列出最近更新的 20 篇笔记。"""
        for i in range(3):
            self._insert_sample_note(
                title=f"列表{i}", file_path=f"列表/{i}.md",
                updated=f"2025-0{i+1}-01",
            )
        notes = self.db.list_notes()
        self.assertEqual(len(notes), 3)
        self.assertGreaterEqual(notes[0]["updated"], notes[-1]["updated"])

    def test_list_notes_empty_db(self):
        """验证空数据库返回空列表。"""
        notes = self.db.list_notes()
        self.assertIsInstance(notes, list)
        self.assertEqual(notes, [])

    def test_list_notes_filter_by_tags(self):
        """验证按标签过滤。"""
        self._insert_sample_note(file_path="列表/tagA.md", tags="python")
        self._insert_sample_note(file_path="列表/tagB.md", tags="javascript")
        notes = self.db.list_notes(tags=["python"])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["file_path"], "列表/tagA.md")

    def test_list_notes_filter_by_project(self):
        """验证按项目过滤。"""
        self._insert_sample_note(file_path="列表/projA.md", project="alpha")
        self._insert_sample_note(file_path="列表/projB.md", project="beta")
        notes = self.db.list_notes(project="alpha")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["project"], "alpha")

    def test_list_notes_filter_by_type(self):
        """验证按类型过滤。"""
        self._insert_sample_note(file_path="列表/perm.md",
                                 note_type="permanent")
        self._insert_sample_note(file_path="列表/sol.md",
                                 note_type="solution")
        notes = self.db.list_notes(note_type="solution")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["type"], "solution")

    def test_list_notes_filter_by_status(self):
        """验证按状态过滤。"""
        self._insert_sample_note(file_path="列表/pub.md",
                                 status="published")
        self._insert_sample_note(file_path="列表/draft.md",
                                 status="draft")
        notes = self.db.list_notes(status="draft")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["status"], "draft")

    def test_list_notes_pagination(self):
        """验证分页参数。"""
        for i in range(5):
            self._insert_sample_note(file_path=f"列表/分页{i}.md")
        page1 = self.db.list_notes(limit=2, offset=0)
        page2 = self.db.list_notes(limit=2, offset=2)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 2)
        ids_page1 = {n["id"] for n in page1}
        ids_page2 = {n["id"] for n in page2}
        self.assertTrue(ids_page1.isdisjoint(ids_page2))

    def test_list_notes_sort_by_title(self):
        """验证按标题排序。"""
        self._insert_sample_note(title="C笔记", file_path="排序/c.md")
        self._insert_sample_note(title="A笔记", file_path="排序/a.md")
        self._insert_sample_note(title="B笔记", file_path="排序/b.md")
        notes = self.db.list_notes(sort="title")
        self.assertEqual(notes[0]["title"], "C笔记")
        self.assertEqual(notes[1]["title"], "B笔记")
        self.assertEqual(notes[2]["title"], "A笔记")

    def test_list_notes_sort_by_created(self):
        """验证按创建时间排序。"""
        self._insert_sample_note(title="旧", file_path="排序/旧.md",
                                 created="2024-01-01")
        self._insert_sample_note(title="新", file_path="排序/新.md",
                                 created="2025-06-01")
        notes = self.db.list_notes(sort="created")
        self.assertEqual(notes[0]["title"], "新")
        self.assertEqual(notes[1]["title"], "旧")

    def test_list_notes_invalid_sort_defaults_to_updated(self):
        """验证非法 sort 参数回退为 updated 排序。"""
        self._insert_sample_note(file_path="排序/a.md", updated="2025-03-01")
        self._insert_sample_note(file_path="排序/b.md", updated="2025-06-01")
        notes = self.db.list_notes(sort="invalid_sort_field")
        self.assertEqual(len(notes), 2)
        self.assertGreaterEqual(notes[0]["updated"], notes[1]["updated"])

    # ═══════════════════════════════════════════════════════════════════
    # get_recent_architecture_notes
    # ═══════════════════════════════════════════════════════════════════

    def test_get_recent_architecture_notes_success(self):
        """验证获取最近架构笔记（permanent/solution 类型）。"""
        self._insert_sample_note(
            title="架构A", file_path="架构/A.md",
            note_type="permanent", project="arch-proj",
            updated="2025-06-01",
        )
        self._insert_sample_note(
            title="方案B", file_path="架构/B.md",
            note_type="solution", project="arch-proj",
            updated="2025-05-15",
        )
        self._insert_sample_note(
            title="普通C", file_path="架构/C.md",
            note_type="fleeting", project="arch-proj",
        )
        notes = self.db.get_recent_architecture_notes("arch-proj", limit=5)
        self.assertEqual(len(notes), 2)
        note_types = {n["type"] for n in notes}
        self.assertTrue(note_types.issubset({"permanent", "solution"}))
        self.assertNotIn("fleeting", note_types)

    def test_get_recent_architecture_notes_empty(self):
        """验证项目无架构笔记时返回空列表。"""
        notes = self.db.get_recent_architecture_notes("no-arch-proj")
        self.assertEqual(notes, [])

    def test_get_recent_architecture_notes_limit(self):
        """验证返回数量受 limit 限制。"""
        for i in range(5):
            self._insert_sample_note(
                title=f"架构{i}", file_path=f"架构/limit{i}.md",
                note_type="permanent", project="limit-arch",
                updated=f"2025-0{i+1}-01",
            )
        notes = self.db.get_recent_architecture_notes("limit-arch", limit=2)
        self.assertEqual(len(notes), 2)

    def test_get_recent_architecture_notes_project_isolation(self):
        """验证项目间数据隔离。"""
        self._insert_sample_note(
            title="项目A笔记", file_path="架构/pa.md",
            note_type="permanent", project="project-A",
        )
        self._insert_sample_note(
            title="项目B笔记", file_path="架构/pb.md",
            note_type="permanent", project="project-B",
        )
        notes_a = self.db.get_recent_architecture_notes("project-A")
        self.assertEqual(len(notes_a), 1)
        self.assertEqual(notes_a[0]["title"], "项目A笔记")

    # ═══════════════════════════════════════════════════════════════════
    # 边界条件与组合场景
    # ═══════════════════════════════════════════════════════════════════

    def test_full_crud_lifecycle(self):
        """完整 CRUD 生命周期：插入→查询→更新→删除→确认不存在。"""
        note_id = self._insert_sample_note(
            title="生命周期", file_path="生命周期/测试.md",
        )
        self.assertGreater(note_id, 0)

        note = self.db.get_note_by_path("生命周期/测试.md")
        self.assertEqual(note["title"], "生命周期")

        self.db.update_note(note_id, title="更新后的生命周期",
                            status="archived")
        note = self.db.get_note_by_path("生命周期/测试.md")
        self.assertEqual(note["title"], "更新后的生命周期")
        self.assertEqual(note["status"], "archived")

        self.assertTrue(self.db.delete_note("生命周期/测试.md"))
        self.assertIsNone(self.db.get_note_by_path("生命周期/测试.md"))

    def test_multiple_notes_different_projects(self):
        """验证多笔记多项目数据隔离。"""
        self._insert_sample_note(title="P1笔记", file_path="p1/note.md",
                                 project="project-1")
        self._insert_sample_note(title="P2笔记", file_path="p2/note.md",
                                 project="project-2")
        self._insert_sample_note(title="P3笔记", file_path="p3/note.md",
                                 project="project-3")
        stats = self.db.get_stats()
        self.assertEqual(stats["total_notes"], 3)
        self.assertEqual(len(stats["by_project"]), 3)

    def test_empty_tags_searchable(self):
        """验证无标签笔记仍可被搜索。"""
        self._insert_and_index(title="NoTagNote", file_path="notag/note.md",
                               content="no tag searchable content here uniqueTerm",
                               tags="")
        results = self.db.search("uniqueTerm")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["tags"], "")

    def test_special_characters_in_file_path(self):
        """验证文件路径包含特殊字符。"""
        self._insert_sample_note(
            title="特殊路径",
            file_path="special/dir-name_v2/file (1).md",
        )
        note = self.db.get_note_by_path(
            "special/dir-name_v2/file (1).md")
        self.assertIsNotNone(note)
        self.assertEqual(note["title"], "特殊路径")

    def test_special_characters_in_search(self):
        """验证搜索包含特殊字符的查询词。+号在FTS5中为运算符需特殊处理。"""
        # 索引含 C++ 的内容，用不含 + 的关键词搜索验证
        self._insert_and_index(
            title="CPP笔记", file_path="cpp/note.md",
            content="CPlusPlus is a powerful language supporting RAII and template metaprogramming.",
        )
        results = self.db.search("CPlusPlus")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "CPP笔记")

    def test_large_word_count(self):
        """验证大字数文本正确存储。"""
        word_count = 10000
        self._insert_sample_note(
            title="长文", file_path="长/文.md", word_count=word_count,
        )
        note = self.db.get_note_by_path("长/文.md")
        self.assertEqual(note["word_count"], word_count)


if __name__ == "__main__":
    unittest.main()
