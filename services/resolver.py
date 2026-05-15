"""标题 → 路径三级解析（回调注入，纯函数）。"""

from dataclasses import dataclass, field
from typing import Callable

FTS5_CONFIDENCE_THRESHOLD = 0.3
MIN_FTS5_SCORE_FOR_AUTO = 0.3


@dataclass
class ResolveResult:
    file_path: str
    title: str
    matched_by: str  # "exact" | "project_filtered" | "fts5"
    candidates: list[dict] = field(default_factory=list)


def resolve_title_to_path(
    title: str,
    project: str | None,
    exact_matcher: Callable[[str, str | None], list[dict]],
    fts5_matcher: Callable[[str, str | None], list[dict]],
) -> ResolveResult | None:
    """三级标题解析。

    1. 精确匹配: exact_matcher(title, project) → 1 条直接返回
    2. project 过滤: 多条精确命中 → 加 project 过滤 → 1 条返回
    3. FTS5 模糊: 精确无命中 → fts5_matcher 搜索 → score > 阈值自动选

    Returns: ResolveResult | None（None 表示完全无法解析）
    """
    # 第一级: 精确匹配
    exact_matches = exact_matcher(title, project)
    if len(exact_matches) == 1:
        return ResolveResult(
            file_path=exact_matches[0]["file_path"],
            title=exact_matches[0]["title"],
            matched_by="exact",
        )

    if len(exact_matches) > 1:
        # 第二级: project 过滤
        if project:
            filtered = [m for m in exact_matches if m.get("project") == project]
            if len(filtered) == 1:
                return ResolveResult(
                    file_path=filtered[0]["file_path"],
                    title=filtered[0]["title"],
                    matched_by="project_filtered",
                )
        # 仍多条 → 返回候选
        return ResolveResult(
            file_path="",
            title="",
            matched_by="ambiguous",
            candidates=exact_matches,
        )

    # 第三级: FTS5 模糊搜索
    fts5_matches = fts5_matcher(title, project)
    if fts5_matches and fts5_matches[0].get("score", 0) >= FTS5_CONFIDENCE_THRESHOLD:
        return ResolveResult(
            file_path=fts5_matches[0]["file_path"],
            title=fts5_matches[0]["title"],
            matched_by="fts5",
        )
    if fts5_matches:
        return ResolveResult(
            file_path="",
            title="",
            matched_by="ambiguous",
            candidates=fts5_matches,
        )

    return None
