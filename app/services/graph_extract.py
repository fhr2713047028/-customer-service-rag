"""实体关系抽取（规则版，阶段十六 GraphRAG）。

最小可行设计：用词典 + 同义词做概念抽取（零 LLM 成本、可单测），
实体粒度 = 概念（Concept）；关系由入库脚本按"分块提及/同块共现"构建。
后续若要升级 LLM 抽取，仅替换本模块的 extract_concepts，图 schema 不变。
"""

# 概念 → 触发词（含同义词/口语表达）
CONCEPT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "运费": ("运费", "邮费", "包邮"),
    "优惠券": ("优惠券", "优惠", "券"),
    "发票": ("发票", "开票"),
    "保修": ("保修", "维修", "售后维修"),
    "换货": ("换货", "换新"),
    "退款": ("退款", "退钱", "退差价"),
    "退货": ("退货", "退换"),
    "物流": ("物流", "快递", "配送", "发货", "揽收", "派送"),
    "订单状态": ("订单状态", "状态代码", "pending_payment", "shipped", "delivered"),
    "签收": ("签收", "收货"),
    "售后": ("售后",),
    "退货时限": ("七天", "7天", "退货时限", "签收之日起"),
}


def extract_concepts(text: str) -> list[str]:
    """从文本提取命中的概念名（按词典顺序，去重）。"""
    return [name for name, synonyms in CONCEPT_SYNONYMS.items() if any(s in text for s in synonyms)]
