"""中文文本处理纯函数：归一化 + jieba 分词 + tsquery 构造。

重要（阶段六 6.1）：PostgreSQL 的 tsvector **不会自动切分中文**。
"支持中文全文检索"的完整机制在这里，分三部分：
1. 生成：入库时用 jieba 分词生成 search_text（空格连接词元）；
2. 索引：search_text 上的表达式 GIN 索引（to_tsvector('simple', search_text)），
   随列更新由 PostgreSQL 自动维护（迁移 #4 与 init_db.py 的原始 SQL）；
3. 查询：用同一分词器构造 tsquery（绑定参数），保证与入库词元口径一致。

全部为纯函数，重点单测。
"""
import re
from pathlib import Path

import jieba

# 自定义词典（电商术语，如"到账"默认会被切成"到/账"）：
# 存在则加载，与入库/查询共享同一份词典，保证分词口径一致
_USERDICT_PATH = Path("data/faq/userdict.txt")
if _USERDICT_PATH.exists():
    jieba.load_userdict(str(_USERDICT_PATH))

# 保留中文/英文/数字词元，丢弃纯标点（"-" 等符号无法成为 tsquery 词元）
_TOKEN_RE = re.compile(r"[\w一-鿿]+")


def normalize(text: str) -> str:
    """全角转半角、统一小写、压缩空白。查询与入库共用，保证口径一致。"""
    chars = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:  # 全角空格
            ch = " "
        elif 0xFF01 <= code <= 0xFF5E:  # 全角符号/字母/数字区间
            ch = chr(code - 0xFEE0)
        chars.append(ch)
    return " ".join("".join(chars).lower().split())


def tokenize_list(text: str) -> list[str]:
    """jieba 分词 + 过滤非词元；返回词元列表。"""
    return [t for t in jieba.lcut(normalize(text)) if _TOKEN_RE.fullmatch(t)]


def build_search_text(text: str) -> str:
    """生成入库用的全文检索字段：空格连接的词元序列。"""
    return " ".join(tokenize_list(text))


def build_tsquery(query: str, operator: str = "&") -> str | None:
    """构造 tsquery 文本（词元以 operator 连接）。

    - "&"（AND）：精确、候选少；"|"（OR）：召回高、候选多；
    - 无有效词元返回 None（调用方应跳过检索而非传空串）。
    返回的是"查询文本"，实际执行时作为绑定参数传入（约束 5）。
    """
    tokens = tokenize_list(query)
    if not tokens:
        return None
    return f" {operator} ".join(tokens)
