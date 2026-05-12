"""Vault MCP Server — graphify 工具 handler 集成测试。

测试 3 个异步 handler：handle_graphify_build / handle_graphify_status /
handle_graphify_query。

使用临时目录 ~/vault-e2e-test/ 和临时 SQLite 数据库，测试后自动清理。
覆盖正常路径、边界路径和错误路径（缺少必填字段、CLI 未安装、目录不存在等）。

运行方式：
    cd C:/Users/Gzlance/scripts/vault-mcp-server
    python -m pytest tests/test_graphify_tools.py -v
    或
    python -m unittest tests.test_graphify_tools -v
"""
import asyncio
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# 将项目根目录加入 sys.path，确保 db 和 tools 模块可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import sqlite3  # noqa: E402
from db import VaultDB  # noqa: E402
from tools.graphify_tools import (  # noqa: E402
    _build_community_md,
    _generate_community_notes,
    handle_graphify_build,
    handle_graphify_query,
    handle_graphify_status,
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
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row

    def _ensure_connected(self):
        """确保连接存在，如已断开则重连。"""
        if self.conn is None:
            self._connect()

    # ── 上下文管理器重写 ──

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


class TestGraphifyTools(unittest.TestCase):
    """Graphify 工具 handler 集成测试。

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
        cls._vaultdb_patch = patch(
            "tools.graphify_tools.VaultDB",
            lambda: cls._shared_db,
        )
        # 补丁 2：将默认 vault 目录重定向到临时目录
        # 注意：必须 patch tools._shared 因为 get_vault_dir() 定义在 _shared 模块中
        cls._vaultdir_patch = patch(
            "tools._shared.DEFAULT_VAULT_DIR",
            cls.vault_dir,
        )
        # 补丁 3：mock _find_graphify_cli，防止意外调用真实 CLI
        cls._cli_patch = patch(
            "tools.graphify_tools._find_graphify_cli",
            return_value="/fake/graphify",
        )
        # 补丁 4：mock _get_git_sha，防止尝试执行真实 git 命令
        cls._git_patch = patch(
            "tools.graphify_tools._get_git_sha",
            return_value="abc12345",
        )
        cls._vaultdb_patch.start()
        cls._vaultdir_patch.start()
        cls._cli_patch.start()
        cls._git_patch.start()

    @classmethod
    def tearDownClass(cls):
        """测试类级别清理：停止补丁，关闭连接，删除临时目录。"""
        cls._vaultdb_patch.stop()
        cls._vaultdir_patch.stop()
        cls._cli_patch.stop()
        cls._git_patch.stop()

        if cls._shared_db:
            cls._shared_db._real_close()

        if cls.vault_dir.exists():
            shutil.rmtree(cls.vault_dir, ignore_errors=True)

    def setUp(self):
        """每个测试方法前清空数据库和文件，确保测试隔离。"""
        db = self._shared_db
        db._ensure_connected()
        for table in ["graphify_builds"]:
            try:
                db.conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        db.conn.commit()

        # 清理 vault 目录下的所有文件，保留目录结构
        for item in self.vault_dir.rglob("*"):
            if item.is_file():
                try:
                    item.unlink()
                except OSError:
                    pass

    # ── 辅助方法 ──

    def _run(self, coro):
        """同步包装器：用 asyncio.run() 运行异步 handler。"""
        return asyncio.run(coro)

    def _parse(self, result):
        """从 handler 返回结果中解析 JSON 字典。"""
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        self.assertTrue(hasattr(result[0], "text"), "返回结果应包含 TextContent 对象")
        return json.loads(result[0].text)

    def _mock_subprocess_success(self, returncode=0, stdout="", stderr=""):
        """创建一个成功的 CompletedProcess mock 上下文管理器。"""
        mock = subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr,
        )
        return patch("subprocess.run", return_value=mock)

    # ═══════════════════════════════════════════════════════════════
    # 1. handle_graphify_build 测试
    # ═══════════════════════════════════════════════════════════════

    def test_build_success(self):
        """正常路径：graphify 构建成功，解析 graph.json 并记录到数据库。"""
        project_name = "test-project"
        project_dir = self.vault_dir / "source" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "main.py").write_text("print('hello')", encoding="utf-8")

        # 预创建 graph.json（模拟 graphify CLI 输出）
        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        graph_json_path = graphify_dir / "graph.json"
        graph_json_path.write_text(json.dumps({
            "nodes": [
                {"name": "main", "community": 1},
                {"name": "helper", "community": 1},
                {"name": "utils", "community": 2},
            ],
            "edges": [
                {"source": "main", "target": "helper"},
                {"source": "helper", "target": "utils"},
            ],
        }), encoding="utf-8")

        with self._mock_subprocess_success():
            result = self._run(handle_graphify_build({
                "project": project_name,
                "project_dir": str(project_dir),
            }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["project"], project_name)
        self.assertEqual(data["node_count"], 3)
        self.assertEqual(data["edge_count"], 2)
        self.assertEqual(data["community_count"], 2)
        self.assertIn("output_dir", data)

        # 验证数据库记录已写入
        build = self._shared_db.get_latest_graphify_build(project_name)
        self.assertIsNotNone(build)
        self.assertEqual(build["node_count"], 3)
        self.assertEqual(build["edge_count"], 2)
        self.assertEqual(build["commit_sha"], "abc12345")

    def test_build_success_elements_format(self):
        """正常路径：graph.json 使用 elements.nodes/elements.edges 嵌套格式。"""
        project_name = "elements-project"
        project_dir = self.vault_dir / "source" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        (graphify_dir / "graph.json").write_text(json.dumps({
            "elements": {
                "nodes": [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}],
                "edges": [{"source": "a", "target": "b"}],
            },
        }), encoding="utf-8")

        with self._mock_subprocess_success():
            result = self._run(handle_graphify_build({
                "project": project_name,
                "project_dir": str(project_dir),
            }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["node_count"], 4)
        self.assertEqual(data["edge_count"], 1)

    def test_build_with_custom_vault_dir(self):
        """正常路径：指定自定义 vault_dir 构建。"""
        custom_vault = self.vault_dir / "custom-vault"
        custom_vault.mkdir(parents=True, exist_ok=True)
        project_name = "custom-vault-project"
        project_dir = self.vault_dir / "source" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        graphify_dir = custom_vault / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        (graphify_dir / "graph.json").write_text(json.dumps({
            "nodes": [{"name": "x"}],
            "edges": [],
        }), encoding="utf-8")

        with self._mock_subprocess_success():
            result = self._run(handle_graphify_build({
                "project": project_name,
                "project_dir": str(project_dir),
                "vault_dir": str(custom_vault),
            }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertIn("output_dir", data)
        self.assertIn("custom-vault", data["output_dir"])

    def test_build_cli_not_found(self):
        """错误路径：graphify CLI 未安装返回 error。"""
        project_dir = self.vault_dir / "source" / "no-cli-project"
        project_dir.mkdir(parents=True, exist_ok=True)

        with patch("tools.graphify_tools._find_graphify_cli", return_value=None):
            result = self._run(handle_graphify_build({
                "project": "no-cli-project",
                "project_dir": str(project_dir),
            }))
        data = self._parse(result)

        self.assertEqual(data["status"], "error")
        self.assertIn("未安装", data["message"])

    def test_build_project_dir_not_exists(self):
        """错误路径：项目目录不存在返回 error。"""
        result = self._run(handle_graphify_build({
            "project": "ghost-project",
            "project_dir": "/nonexistent/path/xyz_12345_does_not_exist",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "error")
        self.assertIn("不存在", data["message"])

    def test_build_subprocess_failure(self):
        """错误路径：subprocess 返回非零退出码。"""
        project_name = "fail-project"
        project_dir = self.vault_dir / "source" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        mock_fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="graphify error: parse failed",
        )
        with patch("subprocess.run", return_value=mock_fail):
            result = self._run(handle_graphify_build({
                "project": project_name,
                "project_dir": str(project_dir),
            }))
        data = self._parse(result)

        self.assertEqual(data["status"], "error")
        self.assertIn("失败", data["message"])
        self.assertIn("stderr", data)

    def test_build_subprocess_timeout(self):
        """错误路径：构建超时返回 error。"""
        project_name = "timeout-project"
        project_dir = self.vault_dir / "source" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(
            cmd=["graphify"], timeout=120,
        )):
            result = self._run(handle_graphify_build({
                "project": project_name,
                "project_dir": str(project_dir),
            }))
        data = self._parse(result)

        self.assertEqual(data["status"], "error")
        self.assertIn("超时", data["message"])

    def test_build_invalid_json(self):
        """错误路径：graph.json 内容非法 JSON 返回 error。"""
        project_name = "bad-json-project"
        project_dir = self.vault_dir / "source" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        (graphify_dir / "graph.json").write_text(
            "this is not json {{{", encoding="utf-8")

        with self._mock_subprocess_success():
            result = self._run(handle_graphify_build({
                "project": project_name,
                "project_dir": str(project_dir),
            }))
        data = self._parse(result)

        self.assertEqual(data["status"], "error")
        self.assertIn("解析失败", data["message"])

    def test_build_missing_project(self):
        """错误路径：缺少 project 字段返回 error。"""
        result = self._run(handle_graphify_build({
            "project_dir": str(self.vault_dir),
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("project", data["message"])

    def test_build_missing_project_dir(self):
        """错误路径：缺少 project_dir 字段返回 error。"""
        result = self._run(handle_graphify_build({
            "project": "test",
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("project_dir", data["message"])

    def test_build_empty_project_name(self):
        """边界路径：project 为空字符串返回 error。"""
        result = self._run(handle_graphify_build({
            "project": "   ",
            "project_dir": str(self.vault_dir),
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("project", data["message"])

    def test_build_empty_project_dir(self):
        """边界路径：project_dir 为空字符串返回 error。"""
        result = self._run(handle_graphify_build({
            "project": "test",
            "project_dir": "   ",
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("project_dir", data["message"])

    # ═══════════════════════════════════════════════════════════════
    # 2. handle_graphify_status 测试
    # ═══════════════════════════════════════════════════════════════

    def test_status_no_builds(self):
        """边界路径：项目从未构建时返回 built=False。"""
        result = self._run(handle_graphify_status({
            "project": "never-built-project",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["project"], "never-built-project")
        self.assertFalse(data["built"])
        self.assertIn("尚未构建", data["message"])

    def test_status_with_builds(self):
        """正常路径：项目有构建记录时返回最新构建信息。"""
        project_name = "built-project"
        # 先插入旧的构建记录
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="older111",
            node_count=10,
            edge_count=20,
            community_count=1,
        )
        import time
        time.sleep(1.1)  # 确保 built_at 时间戳不同
        # 再插入最新的构建记录
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="def67890",
            node_count=42,
            edge_count=100,
            community_count=5,
        )

        result = self._run(handle_graphify_status({
            "project": project_name,
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["built"])
        self.assertEqual(data["project"], project_name)
        self.assertIsNotNone(data["latest_build"])
        self.assertEqual(data["latest_build"]["commit_sha"], "def67890")
        self.assertEqual(data["latest_build"]["node_count"], 42)
        self.assertEqual(data["latest_build"]["edge_count"], 100)
        self.assertEqual(data["latest_build"]["community_count"], 5)
        self.assertIn("built_at", data["latest_build"])

    def test_status_missing_project(self):
        """错误路径：缺少 project 字段返回 error。"""
        result = self._run(handle_graphify_status({}))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("project", data["message"])

    def test_status_empty_project_name(self):
        """边界路径：project 为空字符串返回 error。"""
        result = self._run(handle_graphify_status({"project": "   "}))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("project", data["message"])

    # ═══════════════════════════════════════════════════════════════
    # 3. handle_graphify_query 测试
    # ═══════════════════════════════════════════════════════════════

    def test_query_fuzzy_match(self):
        """正常路径：模糊搜索匹配符号，返回 .md 文件列表。"""
        project_name = "query-project"
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="abc12345",
            node_count=10,
            edge_count=15,
            community_count=3,
        )

        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        (graphify_dir / "Main.md").write_text(
            "# Main 模块\n负责程序入口。", encoding="utf-8")
        (graphify_dir / "helper_utils.md").write_text(
            "# Helper Utils\n辅助工具函数集合。", encoding="utf-8")
        (graphify_dir / "other_module.md").write_text(
            "# Other Module\n与 main 无关的模块。\n这里也提到了 utils 函数。",
            encoding="utf-8")

        result = self._run(handle_graphify_query({
            "project": project_name,
            "symbol": "main",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["symbol"], "main")
        # fuzzy 默认 True：Main.md + other_module.md（正文含 "main"）
        self.assertGreaterEqual(data["count"], 2)
        titles = [r["title"] for r in data["results"]]
        self.assertIn("Main", titles)
        self.assertIn("other_module", titles)
        self.assertNotIn("helper_utils", titles)

        for item in data["results"]:
            self.assertIn("file", item)
            self.assertIn("title", item)
            self.assertNotIn("\\", item["file"])  # 路径使用正斜杠

    def test_query_exact_match(self):
        """正常路径：精确匹配（fuzzy=False），仅匹配完全一致的子串。"""
        project_name = "exact-project"
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="abc12345",
            node_count=5,
            edge_count=8,
            community_count=1,
        )

        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        (graphify_dir / "UserService.md").write_text(
            "# UserService\n用户服务模块。", encoding="utf-8")
        (graphify_dir / "user_service.md").write_text(
            "# user_service\n这是另一个用户服务.", encoding="utf-8")

        # 精确搜索 "UserService"（注意大写 U 和 S）
        result = self._run(handle_graphify_query({
            "project": project_name,
            "symbol": "UserService",
            "fuzzy": False,
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["count"], 1)
        titles = [r["title"] for r in data["results"]]
        self.assertIn("UserService", titles)
        # user_service.md 不含精确子串 "UserService"（大小写不同），不应出现
        self.assertNotIn("user_service", titles)

    def test_query_no_build(self):
        """错误路径：项目未构建过时返回 error。"""
        result = self._run(handle_graphify_query({
            "project": "never-built-query",
            "symbol": "foo",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "error")
        self.assertIn("尚未构建", data["message"])

    def test_query_empty_graphify_dir(self):
        """边界路径：graphify 目录存在但无 .md 文件时返回空结果。"""
        project_name = "empty-dir-project"
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="abc12345",
            node_count=0,
            edge_count=0,
            community_count=0,
        )

        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)

        result = self._run(handle_graphify_query({
            "project": project_name,
            "symbol": "anything",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])

    def test_query_dir_not_exists(self):
        """边界路径：graphify 目录不存在时返回空结果。"""
        project_name = "no-dir-project"
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="abc12345",
            node_count=0,
            edge_count=0,
            community_count=0,
        )

        result = self._run(handle_graphify_query({
            "project": project_name,
            "symbol": "anything",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        # dir 不存在时 handler 不返回 count 字段，只返回 results: []
        self.assertEqual(data.get("count", 0), 0)
        self.assertEqual(data["results"], [])

    def test_query_no_match(self):
        """边界路径：没有 .md 文件匹配符号时返回空结果。"""
        project_name = "no-match-project"
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="abc12345",
            node_count=5,
            edge_count=10,
            community_count=2,
        )

        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        (graphify_dir / "Alpha.md").write_text("# Alpha\n内容", encoding="utf-8")
        (graphify_dir / "Beta.md").write_text("# Beta\n内容", encoding="utf-8")

        result = self._run(handle_graphify_query({
            "project": project_name,
            "symbol": "ZetaNotExists",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["symbol"], "ZetaNotExists")
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])

    def test_query_result_limit(self):
        """正常路径：匹配结果超过 20 条时截断返回前 20 条。"""
        project_name = "limit-project"
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="abc12345",
            node_count=50,
            edge_count=100,
            community_count=10,
        )

        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        for i in range(25):
            (graphify_dir / f"Component_{i:03d}.md").write_text(
                f"# Component_{i:03d}\nCommon component #{i}.", encoding="utf-8")

        result = self._run(handle_graphify_query({
            "project": project_name,
            "symbol": "Common",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 20)

    def test_query_missing_project(self):
        """错误路径：缺少 project 字段返回 error。"""
        result = self._run(handle_graphify_query({"symbol": "foo"}))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("project", data["message"])

    def test_query_missing_symbol(self):
        """错误路径：缺少 symbol 字段返回 error。"""
        result = self._run(handle_graphify_query({"project": "test"}))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("symbol", data["message"])

    def test_query_empty_project_name(self):
        """边界路径：project 为空字符串返回 error。"""
        result = self._run(handle_graphify_query({
            "project": "   ",
            "symbol": "foo",
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("project", data["message"])

    def test_query_empty_symbol(self):
        """边界路径：symbol 为空字符串返回 error。"""
        result = self._run(handle_graphify_query({
            "project": "test",
            "symbol": "   ",
        }))
        data = self._parse(result)
        self.assertEqual(data["status"], "error")
        self.assertIn("symbol", data["message"])

    def test_query_unicode_symbol(self):
        """正常路径：Unicode 符号（中文）模糊搜索。"""
        project_name = "unicode-project"
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="abc12345",
            node_count=3,
            edge_count=4,
            community_count=1,
        )

        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        (graphify_dir / "用户服务模块.md").write_text(
            "# 用户服务模块\n处理用户认证和授权。", encoding="utf-8")
        (graphify_dir / "订单模块.md").write_text(
            "# 订单模块\n处理交易订单。", encoding="utf-8")

        result = self._run(handle_graphify_query({
            "project": project_name,
            "symbol": "用户",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["count"], 1)
        titles = [r["title"] for r in data["results"]]
        self.assertIn("用户服务模块", titles)

    def test_query_unreadable_file_skipped(self):
        """边界路径：目录中存在无法读取的 .md 文件时不崩溃，跳过该文件。"""
        project_name = "badfile-project"
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="abc12345",
            node_count=3,
            edge_count=4,
            community_count=1,
        )

        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        good_file = graphify_dir / "good.md"
        good_file.write_text("# Good\nhas keyword here", encoding="utf-8")
        bad_file = graphify_dir / "bad.md"
        bad_file.write_text("# Bad\nhas keyword too", encoding="utf-8")

        # 对 bad.md 的 read_text 做 patch，使其抛出异常
        original_read_text = Path.read_text

        def _failing_read_text(self, *args, **kwargs):
            if self == bad_file:
                raise OSError("模拟文件读取失败")
            return original_read_text(self, *args, **kwargs)

        with patch("pathlib.Path.read_text", _failing_read_text):
            result = self._run(handle_graphify_query({
                "project": project_name,
                "symbol": "keyword",
            }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        # good.md 能正常读取和匹配
        titles = [r["title"] for r in data["results"]]
        self.assertIn("good", titles)
        # bad.md 读取失败，被跳过，不出现在结果中
        self.assertNotIn("bad", titles)

    def test_query_fuzzy_case_insensitive(self):
        """正常路径：模糊模式下大小写不敏感。"""
        project_name = "case-project"
        self._shared_db.record_graphify_build(
            project=project_name,
            commit_sha="abc12345",
            node_count=1,
            edge_count=0,
            community_count=1,
        )

        graphify_dir = self.vault_dir / "graphify" / project_name
        graphify_dir.mkdir(parents=True, exist_ok=True)
        (graphify_dir / "handler.md").write_text(
            "# Handler\nUPPERCASE Content Here.", encoding="utf-8")

        result = self._run(handle_graphify_query({
            "project": project_name,
            "symbol": "uppercase",
        }))
        data = self._parse(result)

        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["count"], 1)


    # ═══════════════════════════════════════════════════════════════
    # 4. _generate_community_notes 测试
    # ═══════════════════════════════════════════════════════════════

    def test_generate_community_notes_basic(self):
        """正常路径：2 个社区，生成 2 个 Community-*.md 文件。"""
        nodes = [
            {"name": "main", "label": "main", "source_file": "app.py", "community": 1},
            {"name": "helper", "label": "helper", "source_file": "app.py", "community": 1},
            {"name": "utils", "label": "utils", "source_file": "utils.py", "community": 2},
        ]
        links = [
            {"source": "main", "target": "helper", "relation": "calls"},
            {"source": "helper", "target": "utils", "relation": "imports"},
        ]
        output_dir = self.vault_dir / "graphify" / "gen-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, links, output_dir, "test-proj")
        self.assertEqual(count, 2)

        c1 = output_dir / "Community-1.md"
        c2 = output_dir / "Community-2.md"
        self.assertTrue(c1.exists())
        self.assertTrue(c2.exists())

        c1_text = c1.read_text(encoding="utf-8")
        self.assertIn("Community 1", c1_text)
        self.assertIn("**节点数:** 2", c1_text)  # main + helper 不同 label，不会被去重
        self.assertIn("`main`", c1_text)
        self.assertIn("`helper`", c1_text)
        self.assertIn("calls", c1_text)

        c2_text = c2.read_text(encoding="utf-8")
        self.assertIn("Community 2", c2_text)
        self.assertIn("`utils`", c2_text)

    def test_generate_community_notes_empty_nodes(self):
        """边界路径：空节点列表返回 0。"""
        output_dir = self.vault_dir / "graphify" / "empty-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes([], [], output_dir, "test")
        self.assertEqual(count, 0)

    def test_generate_community_notes_no_community_field(self):
        """边界路径：部分节点无 community 字段被跳过。"""
        nodes = [
            {"name": "a", "label": "a", "source_file": "f.py", "community": 1},
            {"name": "b", "label": "b", "source_file": "f.py"},  # 无 community
            {"name": "c", "label": "c", "source_file": "g.py", "community": 1},
        ]
        output_dir = self.vault_dir / "graphify" / "no-comm-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, [], output_dir, "test")
        self.assertEqual(count, 1)

        c1 = output_dir / "Community-1.md"
        c1_text = c1.read_text(encoding="utf-8")
        self.assertIn("`a`", c1_text)
        self.assertIn("`c`", c1_text)
        self.assertNotIn("`b`", c1_text)  # 无 community，不会出现

    def test_generate_community_notes_all_no_community(self):
        """边界路径：所有节点都无 community 字段，返回 0。"""
        nodes = [
            {"name": "a", "label": "a", "source_file": "f.py"},
            {"name": "b", "label": "b", "source_file": "g.py"},
        ]
        output_dir = self.vault_dir / "graphify" / "all-no-comm"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, [], output_dir, "test")
        self.assertEqual(count, 0)

    def test_generate_community_notes_node_dedup(self):
        """正常路径：相同 source_file + label 的节点被去重。"""
        nodes = [
            {"name": "dup1", "label": "foo", "source_file": "a.py", "community": 1},
            {"name": "dup2", "label": "foo", "source_file": "a.py", "community": 1},
            {"name": "unique", "label": "bar", "source_file": "a.py", "community": 1},
        ]
        output_dir = self.vault_dir / "graphify" / "dedup-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, [], output_dir, "test")
        self.assertEqual(count, 1)

        c1 = output_dir / "Community-1.md"
        c1_text = c1.read_text(encoding="utf-8")
        # 去重后只有 2 个节点
        self.assertIn("**节点数:** 2", c1_text)
        # foo 只出现一次（不是两次）
        self.assertEqual(c1_text.count("`foo`"), 1)
        self.assertIn("`bar`", c1_text)

    def test_generate_community_notes_edge_cap(self):
        """边界路径：社区超过 50 条边时截断为 50 条。"""
        nodes = []
        links = []
        for i in range(60):
            node_name = f"n{i}"
            nodes.append({"name": node_name, "label": node_name, "source_file": "x.py", "community": 1})
            if i > 0:
                links.append({"source": "n0", "target": node_name, "relation": "calls"})
        output_dir = self.vault_dir / "graphify" / "edgecap-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, links, output_dir, "test")
        self.assertEqual(count, 1)

        c1 = output_dir / "Community-1.md"
        c1_text = c1.read_text(encoding="utf-8")
        # 只应有 50 条 `--calls-->` 关系
        self.assertEqual(c1_text.count("--calls-->"), 50)

    def test_generate_community_notes_node_cap_per_file(self):
        """边界路径：单个文件中超过 30 个符号时截断显示。"""
        nodes = []
        for i in range(40):
            nodes.append({
                "name": f"f{i}", "label": f"func_{i}",
                "source_file": "big.py", "community": 1,
            })
        output_dir = self.vault_dir / "graphify" / "nodecap-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, [], output_dir, "test")
        self.assertEqual(count, 1)

        c1 = output_dir / "Community-1.md"
        c1_text = c1.read_text(encoding="utf-8")
        # 应包含裁剪提示
        self.assertIn("还有 10 个符号", c1_text)
        # 只应列出 30 个 func_
        self.assertEqual(c1_text.count("`func_"), 30)

    def test_generate_community_notes_community_name_from_source(self):
        """正常路径：社区名取自最高频的源文件名。"""
        nodes = [
            {"name": "a", "label": "a", "source_file": "rare.py", "community": 1},
            {"name": "b", "label": "b", "source_file": "common.py", "community": 1},
            {"name": "c", "label": "c", "source_file": "common.py", "community": 1},
            {"name": "d", "label": "d", "source_file": "common.py", "community": 1},
        ]
        output_dir = self.vault_dir / "graphify" / "name-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, [], output_dir, "test")
        self.assertEqual(count, 1)

        c1 = output_dir / "Community-1.md"
        c1_text = c1.read_text(encoding="utf-8")
        # 最高频 source_file 是 common.py
        self.assertIn("# Community 1: common.py", c1_text)

    def test_generate_community_notes_community_name_fallback(self):
        """边界路径：无 source_file 时社区名降级为 "Community N"。"""
        nodes = [
            {"name": "a", "label": "a", "community": 1},
            {"name": "b", "label": "b", "community": 1},
        ]
        output_dir = self.vault_dir / "graphify" / "name-fallback-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, [], output_dir, "test")
        self.assertEqual(count, 1)

        c1 = output_dir / "Community-1.md"
        c1_text = c1.read_text(encoding="utf-8")
        self.assertIn("# Community 1: Community 1", c1_text)

    def test_generate_community_notes_node_id_field(self):
        """正常路径：节点使用 "id" 字段（而非 "name"）作为标识。"""
        nodes = [
            {"id": "node-a", "label": "Alpha", "source_file": "a.py", "community": 1},
            {"id": "node-b", "label": "Beta", "source_file": "b.py", "community": 1},
        ]
        links = [
            {"source": "node-a", "target": "node-b", "relation": "uses"},
        ]
        output_dir = self.vault_dir / "graphify" / "id-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, links, output_dir, "test")
        self.assertEqual(count, 1)

        c1 = output_dir / "Community-1.md"
        c1_text = c1.read_text(encoding="utf-8")
        self.assertIn("`Alpha`", c1_text)
        self.assertIn("`Beta`", c1_text)
        self.assertIn("uses", c1_text)

    def test_generate_community_notes_links_unmatched_source(self):
        """边界路径：link 的 source 在节点索引中不存在时被跳过。"""
        nodes = [
            {"name": "real", "label": "Real", "source_file": "a.py", "community": 1},
        ]
        links = [
            {"source": "real", "target": "ghost", "relation": "calls"},
            {"source": "ghost", "target": "real", "relation": "calls"},
        ]
        output_dir = self.vault_dir / "graphify" / "unmatched-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, links, output_dir, "test")
        self.assertEqual(count, 1)

        c1 = output_dir / "Community-1.md"
        c1_text = c1.read_text(encoding="utf-8")
        # 只有 source=real 的那条边，target=ghost 正常显示
        self.assertIn("`Real`", c1_text)
        # source=ghost 的边：因为 ghost 不在节点索引中，被跳过
        self.assertEqual(c1_text.count("--calls-->"), 1)

    def test_generate_community_notes_source_location(self):
        """正常路径：节点有 source_location 时输出包含行号。"""
        nodes = [
            {"name": "main", "label": "main", "source_file": "app.py", "source_location": 42, "community": 1},
        ]
        output_dir = self.vault_dir / "graphify" / "loc-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        count = _generate_community_notes(nodes, [], output_dir, "test")
        self.assertEqual(count, 1)

        c1 = output_dir / "Community-1.md"
        c1_text = c1.read_text(encoding="utf-8")
        self.assertIn("(L42)", c1_text)

    def test_generate_community_notes_frontmatter(self):
        """正常路径：生成的 Community-*.md 包含正确的 frontmatter。"""
        nodes = [
            {"name": "f", "label": "f", "source_file": "mod.py", "community": 1},
        ]
        output_dir = self.vault_dir / "graphify" / "fm-test"
        output_dir.mkdir(parents=True, exist_ok=True)

        _generate_community_notes(nodes, [], output_dir, "my-project")

        c1 = output_dir / "Community-1.md"
        c1_text = c1.read_text(encoding="utf-8")
        self.assertIn("title: _COMMUNITY_Community 1", c1_text)
        self.assertIn('tags: ["graphify", "code-graph", "my-project"]', c1_text)
        self.assertIn("type: code-graph", c1_text)
        self.assertIn("project: my-project", c1_text)
        self.assertIn("created: ", c1_text)

    # ═══════════════════════════════════════════════════════════════
    # 5. _build_community_md 测试
    # ═══════════════════════════════════════════════════════════════

    def test_build_community_md_structure(self):
        """正常路径：验证 Markdown 结构包含必要章节。"""
        nodes = [
            {"label": "foo", "source_file": "a.py"},
            {"label": "bar", "source_file": "b.py"},
        ]
        edge_lines = ["- `foo` --calls--> `bar`"]

        md = _build_community_md(
            comm_id=3,
            comm_name="test_module.py",
            nodes=nodes,
            edge_lines=edge_lines,
            project="demo",
        )

        self.assertIn("---", md)
        self.assertIn("title: _COMMUNITY_Community 3", md)
        self.assertIn("project: demo", md)
        self.assertIn("# Community 3: test_module.py", md)
        self.assertIn("**节点数:** 2", md)
        self.assertIn("## 节点", md)
        self.assertIn("### a.py", md)
        self.assertIn("### b.py", md)
        self.assertIn("`foo`", md)
        self.assertIn("`bar`", md)
        self.assertIn("## 关系", md)
        self.assertIn("- `foo` --calls--> `bar`", md)

    def test_build_community_md_no_nodes(self):
        """边界路径：空节点列表不输出节点章节。"""
        md = _build_community_md(1, "empty", [], [], "test")
        self.assertNotIn("## 节点", md)

    def test_build_community_md_no_edges(self):
        """边界路径：空边列表不输出关系章节。"""
        nodes = [{"label": "x", "source_file": "a.py"}]
        md = _build_community_md(1, "no-edges", nodes, [], "test")
        self.assertNotIn("## 关系", md)

    def test_build_community_md_unknown_file(self):
        """边界路径：节点无 source_file 时显示"未知文件"。"""
        nodes = [{"label": "orphan"}]
        md = _build_community_md(1, "test", nodes, [], "test")
        self.assertIn("### 未知文件", md)
        self.assertIn("`orphan`", md)


if __name__ == "__main__":
    unittest.main()
