"""标签重叠检测（纯函数）。"""


def find_overlapping_notes(
    new_tags: list[str],
    overlap_results: list[dict],
    min_overlap: int = 3,
) -> list[dict]:
    """筛选标签重叠 ≥ min_overlap 的已有笔记。

    Args:
        new_tags: 新笔记的标签列表
        overlap_results: db.find_tag_overlaps() 的结果
        min_overlap: 最小重叠标签数（默认 3）

    Returns: [{"title": ..., "file_path": ..., "overlap_count": ..., "overlapping_tags": [...]}, ...]
    """
    return [r for r in overlap_results if r.get("overlap_count", 0) >= min_overlap]


def suggest_action(candidates: list[dict]) -> str:
    """生成用户可执行的操作建议。"""
    if not candidates:
        return ""
    names = "、".join(f'[[{c["title"]}]]' for c in candidates[:3])
    return f"/kb-update {candidates[0]['title']} 更新旧笔记，或 /kb-delete {' '.join(c['title'] for c in candidates)} 删除旧的"
