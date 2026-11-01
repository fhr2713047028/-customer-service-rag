"""RRF 融合纯函数单测（retrieval/hybrid.py）。

使用阶段六 6.2 的官方示例验证：
关键词路：A(1) B(2) C(3)；向量路：C(1) A(2) D(3)
RRF(d) = Σ 1/(k+rank)，k=60：
A = 1/61 + 1/62 ≈ 0.032522
C = 1/63 + 1/61 ≈ 0.032266
B = 1/62         ≈ 0.016129
D = 1/63         ≈ 0.015873
融合顺序：A > C > B > D
"""
from app.models.knowledge_chunk import KnowledgeChunk
from app.retrieval.hybrid import rrf_fuse


def _chunk(cid: int) -> KnowledgeChunk:
    return KnowledgeChunk(id=cid, document_id=1, chunk_index=cid, content=f"c{cid}")


def test_rrf_fusion_with_official_example():
    kw = [(_chunk(1), 0.9), (_chunk(2), 0.7), (_chunk(3), 0.5)]  # A B C
    vec = [(_chunk(3), 0.8), (_chunk(1), 0.6), (_chunk(4), 0.4)]  # C A D
    fused = rrf_fuse(kw, vec, k=60)
    order = [cid for cid, _ in fused]
    assert order == [1, 3, 2, 4]  # A > C > B > D


def test_rrf_dedupes_chunks_across_routes():
    """同一 chunk 在两路都出现：分数累加，只返回一次（去重）。"""
    kw = [(_chunk(1), 0.9)]
    vec = [(_chunk(1), 0.8), (_chunk(2), 0.5)]
    fused = rrf_fuse(kw, vec, k=60)
    assert [cid for cid, _ in fused] == [1, 2]
    # 累加后的融合分 = 关键词路第 1 名 + 向量路第 1 名 = 1/61 + 1/61
    assert abs(fused[0][1] - (1 / 61 + 1 / 61)) < 1e-9


def test_rrf_k_affects_smoothing():
    """k 越大，排名间的差异被平滑得越小（理解常数含义）。

    用同一路内第 1 名与第 2 名的分数差验证（两路第 1 名同分，不能用作比较）。
    """
    kw = [(_chunk(1), 0.9), (_chunk(3), 0.5)]  # chunk1 在关键词路排第 1，chunk3 排第 2
    vec = [(_chunk(2), 0.8)]
    fused_large_k = rrf_fuse(kw, vec, k=1000)
    fused_small_k = rrf_fuse(kw, vec, k=1)
    # chunk1 与 chunk3 的融合分差：1/(k+1) - 1/(k+2)，k 越大差越小
    gap_large = fused_large_k[0][1] - fused_large_k[-1][1]
    gap_small = fused_small_k[0][1] - fused_small_k[-1][1]
    assert gap_small > gap_large


def test_rrf_empty_inputs():
    assert rrf_fuse([], []) == []
    fused = rrf_fuse([(_chunk(1), 0.9)], [])
    assert [cid for cid, _ in fused] == [1]
