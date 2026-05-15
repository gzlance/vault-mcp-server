"""wikilink 检测与自动链接生成（从 tools 层抽离的纯函数）。"""

import re

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[^\]\]]*)?\]\]")


def to_kebab(title: str) -> str:
    """标题转 kebab-case 文件名。"""
    name = title.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    return name.strip("-")


def extract_wikilinks(content: str) -> list[dict]:
    """从 Markdown 正文中提取 [[wikilink]] 目标。"""
    targets = []
    for match in WIKILINK_RE.finditer(content):
        target_title = match.group(1).strip()
        start = max(0, match.start() - 30)
        end = min(len(content), match.end() + 30)
        context = content[start:end].replace("\n", " ")
        targets.append({"target": to_kebab(target_title) + ".md", "context": context})
    return targets


def find_unlinked_titles(content: str, known_titles: list[str]) -> list[dict]:
    """检测正文中已知标题的纯文本出现（未被 [[]] 包裹）。

    返回列表，每元素 {"start": int, "end": int, "title": str}，
    按 start 降序排列，方便从后往前替换避免偏移。
    """
    existing_ranges = [(m.start(), m.end()) for m in WIKILINK_RE.finditer(content)]

    def _inside_existing(pos: int) -> bool:
        return any(s <= pos < e for s, e in existing_ranges)

    spans = []
    for title in known_titles:
        if not title or not title.strip():
            continue
        title_clean = title.strip()
        pattern = re.compile(re.escape(title_clean), re.IGNORECASE)
        for match in pattern.finditer(content):
            if _inside_existing(match.start()):
                continue
            if match.start() < 4:  # 跳过 YAML frontmatter 区域
                continue
            spans.append({"start": match.start(), "end": match.end(), "title": title_clean})

    # 去重：按 start 排序，重叠区间保留更长的
    spans.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))
    merged = []
    for span in spans:
        if merged and span["start"] < merged[-1]["end"]:
            if (span["end"] - span["start"]) > (merged[-1]["end"] - merged[-1]["start"]):
                merged[-1] = span
        else:
            merged.append(span)
    merged.sort(key=lambda s: s["start"], reverse=True)
    return merged


def auto_link_titles(content: str, known_titles: list[str]) -> tuple[str, int]:
    """将正文中的纯文本标题替换为 [[title]] wikilink。

    Returns: (new_content, count)
    """
    spans = find_unlinked_titles(content, known_titles)
    new_content = content
    for span in spans:
        new_content = new_content[: span["start"]] + f"[[{span['title']}]]" + new_content[span["end"] :]
    return new_content, len(spans)


def suggest_wikilinks(content: str, known_titles: list[str]) -> list[dict]:
    """返回可自动 wikilink 的建议列表。"""
    spans = find_unlinked_titles(content, known_titles)
    suggestions = []
    for span in spans:
        start_ctx = max(0, span["start"] - 30)
        end_ctx = min(len(content), span["end"] + 30)
        context = content[start_ctx:end_ctx].replace("\n", " ")
        suggestions.append({"target": to_kebab(span["title"]) + ".md", "context": context})
    return suggestions
