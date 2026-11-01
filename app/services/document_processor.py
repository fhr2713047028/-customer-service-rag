"""文档处理纯函数（阶段四核心，全部可单测，无 DB/IO 依赖）。

流程：Markdown 文本 → 解析（标题/小节/行号）→ 清洗 → 分块 → 元数据。

v1 设计决策（简化、可验证）：
- 输入格式只支持 Markdown（PDF 解析等复杂度暂不引入）；
- 第一个 `#` 行 = 文档标题，`##` 行 = 小节边界（天然分块点）；
- 分块：每个小节一块；超过 chunk_size（默认 500 字符）的小节按
  overlap（默认 50 字符）重叠窗口续切，保证语义衔接；
- 清洗规则：去 BOM、行尾空白、空行、纯符号分隔行、相邻重复行；
- 每块元数据：文档标题、小节标题、源行号、字符数（溯源与质检用）。
"""
import re
from dataclasses import dataclass, field

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
HARD_MAX_CHUNK_SIZE = 600  # 质检硬上限（chunk_size 500 + 安全余量）


@dataclass
class ParsedDocument:
    title: str
    # (小节标题, 原始内容, 起始行号)；标题为 "" 表示 H1 之后第一个 H2 之前的前言
    sections: list[tuple[str, str, int]]


@dataclass
class ChunkDraft:
    index: int
    content: str
    metadata: dict


def parse_markdown(text: str) -> ParsedDocument:
    """解析 Markdown：第一个 H1 为文档标题，每个 H2 为小节边界。"""
    title: str | None = None
    sections: list[tuple[str, str, int]] = []
    current_title = ""
    current_lines: list[str] = []
    current_start = 1

    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.startswith("# "):
            if title is None:  # 只认第一个 H1 为文档标题
                title = line[2:].strip()
                current_start = lineno + 1
            continue
        if line.startswith("## "):
            if current_lines or current_title:
                sections.append((current_title, "\n".join(current_lines), current_start))
            current_title = line[3:].strip()
            current_lines = []
            current_start = lineno + 1
            continue
        current_lines.append(line)

    if current_lines or current_title:
        sections.append((current_title, "\n".join(current_lines), current_start))

    if title is None:
        raise ValueError("文档缺少一级标题（# 标题）")
    return ParsedDocument(title=title, sections=sections)


# 纯分隔符/符号行（如 "---"、"***"、"====="），无信息量，直接丢弃
_INVALID_LINE_RE = re.compile(r"^[\s\-—_=*#·•|]+$")


def clean_text(text: str) -> str:
    """清洗：去 BOM、行尾空白、空行、纯符号行、块引用行、严格相邻的重复行。

    - 块引用行（> 开头）视为文档注解（如"模拟规则"声明），不属于知识内容；
    - 去重只针对严格相邻的相同行 —— 中间隔了任何行（即使该行随后被清洗掉）
      都不算相邻，避免误删有用内容。
    """
    text = text.lstrip("﻿")
    cleaned: list[str] = []
    prev_stripped: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:  # 空行
            prev_stripped = None  # 阻断相邻链
            continue
        if _INVALID_LINE_RE.match(stripped):  # 纯符号行
            prev_stripped = stripped
            continue
        if stripped.startswith(">"):  # 块引用：文档注解，不进知识内容
            prev_stripped = stripped
            continue
        if stripped == prev_stripped:  # 严格相邻的重复行
            continue
        cleaned.append(line.rstrip())
        prev_stripped = stripped
    return "\n".join(cleaned).strip()


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """长文本按重叠窗口切分：后一块的开头重复前一块的结尾（语义衔接）。"""
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return parts


def build_chunk_metadata(
    doc_title: str, section_title: str, source_line: int, content: str
) -> dict:
    return {
        "doc_title": doc_title,
        "section": section_title or "前言",
        "source_line": source_line,
        "char_count": len(content),
    }


def chunk_document(
    parsed: ParsedDocument,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[ChunkDraft]:
    """清洗 + 分块 + 生成元数据；清洗后无有效内容抛 ValueError。"""
    drafts: list[ChunkDraft] = []
    index = 0
    for section_title, raw, source_line in parsed.sections:
        content = clean_text(raw)
        if not content:
            continue
        for part in _split_long(content, chunk_size, chunk_overlap):
            drafts.append(
                ChunkDraft(
                    index=index,
                    content=part,
                    metadata=build_chunk_metadata(
                        parsed.title, section_title, source_line, part
                    ),
                )
            )
            index += 1
    if not drafts:
        raise ValueError("文档清洗后没有有效内容")
    return drafts
