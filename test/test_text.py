"""中文分词与 tsquery 构造单测（core/text.py）。"""
from app.core.text import build_search_text, build_tsquery, normalize, tokenize_list


def test_normalize_fullwidth_to_halfwidth():
    assert normalize("ＡＢＣ１２３") == "abc123"
    assert normalize("退款，到账！") == "退款,到账!"
    assert normalize("  多余   空白  ") == "多余 空白"


def test_tokenize_filters_punctuation():
    tokens = tokenize_list("商品型号 A100-X 有什么规格？")
    assert "a100" in tokens
    assert "x" in tokens
    assert "-" not in tokens  # 纯符号不能成为 tsquery 词元
    assert "？" not in tokens


def test_build_search_text_joins_tokens():
    text = build_search_text("退货政策说明")
    assert text == "退货 政策 说明"


def test_build_tsquery_and_or():
    assert build_tsquery("退款 到账", operator="&") == "退款 & 到账"
    assert build_tsquery("退款 到账", operator="|") == "退款 | 到账"


def test_build_tsquery_empty_returns_none():
    assert build_tsquery("？？？") is None
    assert build_tsquery("") is None
