"""ORM 模型汇总：必须在这里 import 所有模型。

alembic 的 autogenerate 和 init_db 的 create_all 都依赖
Base.metadata 收集到全部表；漏 import 的表不会被建出来。

2026-10-30 按用户确认的表名清单：kb_documents/kb_chunks 更名为
knowledge_documents/knowledge_chunks；新增 query_logs；faqs 未列入清单，暂不建模。
"""
from app.models.user import User
from app.models.product import Product
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.logistics import Logistics
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.query_log import QueryLog

__all__ = [
    "User",
    "Product",
    "Order",
    "OrderItem",
    "Logistics",
    "KnowledgeDocument",
    "KnowledgeChunk",
    "QueryLog",
]
