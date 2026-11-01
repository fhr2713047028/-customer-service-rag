"""文档处理纯函数单测（services/document_processor.py）。"""
import pytest

from app.services.document_processor import (
    build_chunk_metadata,
    chunk_document,
    clean_text,
    parse_markdown,
)

SAMPLE = """# 测试文档标题

前言内容第一行。

## 第一节

第一节内容。
第一节补充内容。

## 第二节

第二节内容。
"""


def test_parse_markdown_title_and_sections():
    parsed = parse_markdown(SAMPLE)
    assert parsed.title == "测试文档标题"
    assert len(parsed.sections) == 3
    # (小节标题, 内容, 起始行号)：前言标题为空
    assert parsed.sections[0][0] == ""
    assert "前言内容第一行" in parsed.sections[0][1]
    assert parsed.sections[1][0] == "第一节"
    assert parsed.sections[2][0] == "第二节"


def test_parse_markdown_requires_h1():
    with pytest.raises(ValueError):
        parse_markdown("只有正文没有标题\n## 小节\n内容")


def test_clean_text_rules():
    dirty = "﻿# 标题  \n\n---\n重复行\n重复行\n有效内容\n***\n有效内容\n> 模拟规则声明\n正文"
    cleaned = clean_text(dirty)
    assert "﻿" not in cleaned           # BOM 去除
    assert "---" not in cleaned              # 纯符号行去除
    assert "***" not in cleaned
    assert cleaned.count("重复行") == 1      # 严格相邻的重复行去重
    assert cleaned.count("有效内容") == 2    # 被符号行隔开的保留
    assert "模拟规则声明" not in cleaned     # 块引用行（文档注解）不进入知识内容
    assert cleaned.endswith("正文")
    assert "  " not in cleaned               # 行尾空白去除


def test_chunk_short_sections_one_chunk_each():
    drafts = chunk_document(parse_markdown(SAMPLE))
    assert [d.index for d in drafts] == [0, 1, 2]
    assert drafts[0].metadata["section"] == "前言"
    assert drafts[1].metadata["section"] == "第一节"
    assert drafts[2].metadata["section"] == "第二节"
    # 每个分块都带完整元数据
    for d in drafts:
        assert d.metadata["doc_title"] == "测试文档标题"
        assert d.metadata["char_count"] == len(d.content)
        assert d.metadata["source_line"] > 0


def test_chunk_long_section_splits_with_overlap():
    long_text = "长文档内容" * 150  # 750 字符，超过默认 500
    parsed = parse_markdown(f"# 长文档\n## 长小节\n{long_text}\n")
    drafts = chunk_document(parsed, chunk_size=500, chunk_overlap=50)
    assert len(drafts) == 2
    assert len(drafts[0].content) == 500
    # 重叠衔接：后一块的开头等于前一块的结尾
    assert drafts[1].content[:50] == drafts[0].content[-50:]
    # 元数据保持一致性
    assert drafts[0].metadata["section"] == "长小节"


def test_chunk_empty_document_raises():
    parsed = parse_markdown("# 空文档\n---\n\n")
    with pytest.raises(ValueError):
        chunk_document(parsed)


def test_build_chunk_metadata_fields():
    meta = build_chunk_metadata("标题", "小节", 10, "abc")
    assert meta == {"doc_title": "标题", "section": "小节", "source_line": 10, "char_count": 3}
