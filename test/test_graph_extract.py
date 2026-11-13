"""图实体抽取纯函数单测（services/graph_extract.py，阶段十六）。"""
from app.services.graph_extract import extract_concepts


def test_extract_single_concept():
    assert extract_concepts("退货的运费谁出") == ["运费", "退货"]  # 按词典顺序


def test_extract_synonyms():
    assert "物流" in extract_concepts("快递一直不更新怎么办")
    assert "运费" in extract_concepts("邮费怎么算")
    assert "退货时限" in extract_concepts("签收之日起 7 天内能退吗")


def test_extract_none():
    assert extract_concepts("今天天气怎么样") == []


def test_extract_no_duplicates():
    text = "退货的运费和退货的流程"
    concepts = extract_concepts(text)
    assert concepts.count("退货") == 1
