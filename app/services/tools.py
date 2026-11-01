"""受控业务工具（阶段八 8.1/8.2）。

第一版不引入 Agent 框架：工具是**显式的 Pydantic 输入模型 + 受控处理函数**。
每条路径都有明确的输入、输出和权限边界：

- 工具参数经 Pydantic 校验（如订单号必须 8~32 位字母数字）；
- 身份只来自 JWT（user 参数由 get_current_user 注入）——
  **用户消息里的任何内容（包括"忽略权限检查"）都无法影响身份与权限**；
- 数据库访问一律走受控 ORM / 参数化查询（retrieval 层），
  工具函数不直接写 SQL。

后续若要展示 Agent 能力（第二版），可在此基础上接 Function Calling，
工具选择正确率与参数错误处理用同一套测试验证。
"""
from pydantic import BaseModel, Field

from app.models.user import User
from app.retrieval.structured import get_order_by_no_for_user, search_products
from app.services.order_service import order_to_out
from app.services.structured_answer import answer_logistics, answer_order_status


class OrderLookupInput(BaseModel):
    """订单查询工具入参：只接受订单号，无任何用户身份字段。"""

    order_no: str = Field(pattern=r"^[A-Za-z0-9]{8,32}$", description="对外订单号")


class LogisticsLookupInput(BaseModel):
    tracking_no: str = Field(min_length=4, max_length=64, description="物流单号")


class ProductSearchInput(BaseModel):
    keyword: str = Field(min_length=1, max_length=100, description="商品关键词")


async def order_lookup(session, user: User, params: OrderLookupInput) -> dict:
    """订单查询工具：归属校验在 SQL 层 + 服务层双重强制。"""
    return await answer_order_status(session, user, params.order_no)


async def logistics_lookup(session, user: User, params: LogisticsLookupInput) -> dict:
    """物流查询工具（按单号）：归属校验同上。"""
    logistics = await get_order_by_no_for_user(session, params.tracking_no, user.id)
    # 注：该路径 v1 复用订单号逻辑；独立物流单号查询走 logistics API（GET /logistics/{tracking_no}）
    if logistics is None:
        return {
            "answer": "未查询到对应记录，请核对物流单号或订单号。",
            "answer_type": "template",
            "sources": [],
            "confidence": "low",
        }
    return await answer_logistics(session, user)


async def product_search(session, user: User, params: ProductSearchInput) -> dict:
    """商品查询工具：公开数据，但参数同样经 Pydantic 校验。"""
    total, products = await search_products(
        session, keyword=params.keyword, category=None, page=1, page_size=3
    )
    if not products:
        return {
            "answer": "未找到相关商品，请提供商品名称、型号或关键词。",
            "answer_type": "template",
            "sources": [],
            "confidence": "low",
        }
    summary = "；".join(f"{p.name}（{p.sku}）售价 {p.price} 元" for p in products)
    return {
        "answer": f"为您找到以下商品：{summary}。",
        "answer_type": "template",
        "sources": [
            {
                "type": "product",
                "doc_title": p.name,
                "chunk_id": None,
                "section": None,
                "score": None,
                "order_no": None,
            }
            for p in products
        ],
        "confidence": "high",
    }


# 工具注册表：名称 → (入参模型, 处理函数)。
# 后续 Function Calling 版本中，此表即模型的可用工具清单。
TOOLS: dict[str, tuple[type[BaseModel], object]] = {
    "order_lookup": (OrderLookupInput, order_lookup),
    "logistics_lookup": (LogisticsLookupInput, logistics_lookup),
    "product_search": (ProductSearchInput, product_search),
}
