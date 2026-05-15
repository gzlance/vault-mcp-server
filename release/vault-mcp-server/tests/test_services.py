"""services/ 纯函数单元测试（无需数据库）。"""
import pytest

from services.validator import (
    validate_title, validate_tags, validate_type, validate_wikilink_count,
)
from services.tags import find_overlapping_notes, suggest_action
from services.resolver import resolve_title_to_path, ResolveResult
from services.wikilink import to_kebab, extract_wikilinks, auto_link_titles, suggest_wikilinks


class TestValidator:
    def test_validate_title_empty(self):
        assert validate_title("") == "标题不能为空"
        assert validate_title("   ") == "标题不能为空"

    def test_validate_title_too_long(self):
        long_title = "x" * 201
        assert "过长" in validate_title(long_title)

    def test_validate_title_valid(self):
        assert validate_title("正常标题") is None
        assert validate_title("x" * 200) is None

    def test_validate_tags_not_list(self):
        assert "必须是列表类型" in validate_tags("not a list")

    def test_validate_tags_non_string(self):
        assert "标签值必须为字符串" in validate_tags([123])

    def test_validate_tags_too_long(self):
        long_tag = "x" * 51
        assert "过长" in validate_tags([long_tag])

    def test_validate_tags_valid(self):
        assert validate_tags(["python", "测试"]) is None
        assert validate_tags([]) is None

    def test_validate_type_invalid(self):
        assert "无效的笔记类型" in validate_type("invalid_type")

    def test_validate_type_valid(self):
        for t in ["permanent", "solution", "concept", "tool", "session-log", "code-graph"]:
            assert validate_type(t) is None

    def test_validate_wikilink_count_permanent_few(self):
        msg = validate_wikilink_count("permanent", 1)
        assert msg and "2 个 wikilink" in msg

    def test_validate_wikilink_count_permanent_ok(self):
        assert validate_wikilink_count("permanent", 3) is None

    def test_validate_wikilink_count_other_type(self):
        assert validate_wikilink_count("solution", 0) is None


class TestTags:
    def test_find_overlapping_notes_below_threshold(self):
        result = find_overlapping_notes(["a", "b"], [
            {"title": "test", "overlap_count": 2}
        ])
        assert result == []

    def test_find_overlapping_notes_meets_threshold(self):
        result = find_overlapping_notes(["a", "b", "c"], [
            {"title": "test", "file_path": "x.md", "overlap_count": 3, "overlapping_tags": ["a", "b", "c"]}
        ])
        assert len(result) == 1

    def test_suggest_action_empty(self):
        assert suggest_action([]) == ""

    def test_suggest_action_with_candidates(self):
        candidates = [{"title": "笔记A", "file_path": "a.md"}]
        result = suggest_action(candidates)
        assert "/kb-update" in result
        assert "笔记A" in result

    def test_suggest_action_multiple(self):
        candidates = [
            {"title": "A", "file_path": "a.md"},
            {"title": "B", "file_path": "b.md"},
            {"title": "C", "file_path": "c.md"},
        ]
        result = suggest_action(candidates)
        assert "A" in result


class TestResolver:
    def test_exact_match_single(self):
        result = resolve_title_to_path(
            title="test",
            project="p",
            exact_matcher=lambda t, p: [{"file_path": "p/test.md", "title": "test"}],
            fts5_matcher=lambda t, p: [],
        )
        assert result is not None
        assert result.matched_by == "exact"
        assert result.file_path == "p/test.md"

    def test_exact_multiple_project_filtered(self):
        result = resolve_title_to_path(
            title="test",
            project="p",
            exact_matcher=lambda t, p: [
                {"file_path": "p/test.md", "title": "test", "project": "p"},
                {"file_path": "q/test.md", "title": "test", "project": "q"},
            ],
            fts5_matcher=lambda t, p: [],
        )
        assert result is not None
        assert result.matched_by == "project_filtered"

    def test_exact_multiple_ambiguous(self):
        result = resolve_title_to_path(
            title="test",
            project=None,
            exact_matcher=lambda t, p: [
                {"file_path": "a/test.md", "title": "test"},
                {"file_path": "b/test.md", "title": "test"},
            ],
            fts5_matcher=lambda t, p: [],
        )
        assert result is not None
        assert result.matched_by == "ambiguous"
        assert len(result.candidates) == 2

    def test_fts5_match(self):
        result = resolve_title_to_path(
            title="test",
            project="p",
            exact_matcher=lambda t, p: [],
            fts5_matcher=lambda t, p: [
                {"file_path": "p/fuzzy.md", "title": "fuzzy test", "score": 0.5}
            ],
        )
        assert result is not None
        assert result.matched_by == "fts5"

    def test_fts5_ambiguous(self):
        result = resolve_title_to_path(
            title="test",
            project=None,
            exact_matcher=lambda t, p: [],
            fts5_matcher=lambda t, p: [
                {"file_path": "x.md", "title": "x", "score": 0.2},
            ],
        )
        assert result is not None
        assert result.matched_by == "ambiguous"

    def test_resolve_result_fields(self):
        r = ResolveResult(file_path="/tmp", title="T", matched_by="exact", candidates=[{"x": 1}])
        assert r.file_path == "/tmp"
        assert r.title == "T"
        assert r.matched_by == "exact"
        assert len(r.candidates) == 1
