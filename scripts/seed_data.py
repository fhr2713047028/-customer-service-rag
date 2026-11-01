"""合成测试数据初始化脚本（synthetic / demo）。

数据规模（2026-10-30 用户确认）：
- users:            20 个测试用户（demo_user_001 为管理员）
- products:         40 个商品（合成目录，描述带 [synthetic] 标记）
- orders:           100 个订单（订单号 SYN 前缀，含 1~3 条明细，金额由明细累加得出）
- order_items:      随订单生成
- logistics:        100 条物流行（每单一条）× 每条 3 个轨迹事件 = 300 条物流记录

特性：
- 固定随机种子（42）：每次运行生成完全相同的数据，可复现；
- 幂等：先 TRUNCATE 相关表再重新写入（CASCADE 会连带清空引用表 query_logs），
  重复执行结果一致；
- 全部数据为合成测试数据，不冒充真实业务数据。

运行（项目根目录）：
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python -m scripts.seed_data
"""
import asyncio
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from faker import Faker
from sqlalchemy import text

from app.db.session import SessionFactory
from app.models.logistics import Logistics
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.user import User
from app.services.business import derived_logistics_status

SEED = 42
NUM_USERS = 20
NUM_PRODUCTS = 40
NUM_ORDERS = 100
TIMELINE_EVENTS_PER_LOGISTICS = 3

# 合成商品目录（synthetic）：(名称, 类目, 价格区间)
PRODUCT_CATALOG = [
    ("电热水壶", "家电", (49.9, 299.0)),
    ("空气炸锅", "家电", (199.0, 899.0)),
    ("手持吸尘器", "家电", (99.0, 699.0)),
    ("加湿器", "家电", (39.9, 259.0)),
    ("电饭煲", "家电", (129.0, 799.0)),
    ("蓝牙耳机", "数码", (39.9, 899.0)),
    ("智能手表", "数码", (199.0, 1999.0)),
    ("移动电源", "数码", (59.0, 299.0)),
    ("机械键盘", "数码", (99.0, 699.0)),
    ("高清摄像头", "数码", (79.0, 499.0)),
    ("记忆棉枕头", "家居", (49.0, 299.0)),
    ("遮光窗帘", "家居", (69.0, 399.0)),
    ("懒人沙发", "家居", (199.0, 999.0)),
    ("落地灯", "家居", (89.0, 599.0)),
    ("收纳箱", "家居", (19.9, 129.0)),
    ("不粘炒锅", "厨具", (69.0, 399.0)),
    ("陶瓷餐具套装", "厨具", (99.0, 599.0)),
    ("保温饭盒", "厨具", (29.9, 159.0)),
    ("厨房剪刀", "厨具", (9.9, 69.0)),
    ("砧板", "厨具", (19.9, 129.0)),
    ("纯棉T恤", "服饰", (29.9, 129.0)),
    ("连帽卫衣", "服饰", (79.0, 299.0)),
    ("运动鞋", "服饰", (129.0, 599.0)),
    ("防晒衣", "服饰", (49.0, 199.0)),
    ("双肩包", "服饰", (59.0, 299.0)),
    ("坚果礼盒", "食品", (39.9, 199.0)),
    ("挂耳咖啡", "食品", (19.9, 99.0)),
    ("蜂蜜柚子茶", "食品", (29.9, 129.0)),
    ("每日坚果", "食品", (29.9, 159.0)),
    ("燕麦片", "食品", (19.9, 89.0)),
    ("电动牙刷", "个护", (99.0, 399.0)),
    ("洗发水套装", "个护", (39.9, 199.0)),
    ("保湿面霜", "个护", (59.0, 299.0)),
    ("剃须刀", "个护", (49.0, 699.0)),
    ("吹风机", "个护", (79.0, 499.0)),
    ("中性笔套装", "文具", (9.9, 49.0)),
    ("笔记本", "文具", (9.9, 69.0)),
    ("手账本", "文具", (19.9, 99.0)),
    ("文件收纳夹", "文具", (9.9, 59.0)),
    ("马克笔套装", "文具", (19.9, 99.0)),
]

CARRIERS = ["顺丰速运", "中通快递", "圆通速递", "韵达快递", "京东物流"]

ORDER_STATUSES = [
    "pending_payment", "paid", "shipped", "delivered",
    "completed", "cancelled", "refunding", "refunded",
]
ORDER_STATUS_WEIGHTS = [0.08, 0.12, 0.15, 0.22, 0.20, 0.10, 0.05, 0.08]



def build_timeline(faker: Faker, shipped_at: datetime, carrier: str, city_from: str, city_to: str) -> list[dict]:
    """固定 3 个轨迹事件：揽收 → 中转 → 派送（synthetic 简化）。"""
    return [
        {"time": shipped_at.isoformat(), "location": city_from, "description": f"{carrier}已揽收"},
        {
            "time": (shipped_at + timedelta(days=1)).isoformat(),
            "location": faker.city(),
            "description": "运输中，已到达中转站",
        },
        {
            "time": (shipped_at + timedelta(days=2)).isoformat(),
            "location": city_to,
            "description": "派送中",
        },
    ]


async def seed() -> None:
    rng = random.Random(SEED)
    faker = Faker("zh_CN")
    Faker.seed(SEED)

    async with SessionFactory() as session:
        # 幂等：清空相关表并重置自增序列；CASCADE 会连带清空引用它们的表（如 query_logs）
        await session.execute(
            text("TRUNCATE users, products, orders, order_items, logistics RESTART IDENTITY CASCADE")
        )

        # 1) 用户：20 个，demo_user_001 为管理员
        users = []
        for i in range(1, NUM_USERS + 1):
            users.append(
                User(
                    username=f"demo_user_{i:03d}",
                    phone=f"139{rng.randint(10000000, 99999999)}",
                    email=f"demo_user_{i:03d}@example.com",
                    is_admin=(i == 1),
                )
            )
        session.add_all(users)

        # 2) 商品：40 个（目录固定，价格/库存由种子决定）
        products = []
        for idx, (name, category, (lo, hi)) in enumerate(PRODUCT_CATALOG, start=1):
            products.append(
                Product(
                    sku=f"SKU{idx:04d}",
                    name=name,
                    category=category,
                    description=f"[synthetic] {name} 测试商品描述",
                    price=Decimal(f"{rng.uniform(lo, hi):.2f}"),
                    stock=rng.randint(0, 500),
                    status="off_sale" if rng.random() < 0.1 else "on_sale",
                )
            )
        session.add_all(products)
        await session.flush()  # 拿到 users/products 的主键 id

        # 3) 订单 + 明细 + 物流：100 单，金额由明细累加
        start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        end = datetime(2026, 10, 30, tzinfo=timezone.utc)
        span_seconds = int((end - start).total_seconds())

        for i in range(1, NUM_ORDERS + 1):
            user = rng.choice(users)
            created_at = start + timedelta(seconds=rng.randint(0, span_seconds))
            order_no = f"SYN{created_at:%Y%m%d}{i:04d}"
            status = rng.choices(ORDER_STATUSES, weights=ORDER_STATUS_WEIGHTS, k=1)[0]

            order = Order(
                order_no=order_no,
                user_id=user.id,  # 直接赋 id（等价于 order.user = user，避免触发懒加载护栏）
                status=status,
                total_amount=Decimal("0"),  # 先占位，明细生成后累加
                receiver_name=faker.name(),
                receiver_phone=faker.phone_number(),
                receiver_address=faker.address(),
                created_at=created_at,
                updated_at=created_at,
            )

            total = Decimal("0")
            for _ in range(rng.randint(1, 3)):
                product = rng.choice(products)
                qty = rng.randint(1, 3)
                OrderItem(
                    order=order,
                    product_id=product.id,
                    product_name_snapshot=product.name,  # 下单时快照
                    sku_snapshot=product.sku,
                    price_snapshot=product.price,
                    quantity=qty,
                )
                total += product.price * qty
            order.total_amount = total
            session.add(order)

            # 物流：每单 1 行 × 3 个轨迹事件
            carrier = rng.choice(CARRIERS)
            city_from, city_to = faker.city(), faker.city()
            shipped_at = created_at + timedelta(hours=2)
            last_event_time = shipped_at + timedelta(days=2)
            session.add(
                Logistics(
                    order=order,
                    tracking_no=f"SYN{i:012d}",
                    carrier=carrier,
                    status=derived_logistics_status(status),  # 业务规则集中管理（services/business.py）
                    timeline=build_timeline(faker, shipped_at, carrier, city_from, city_to),
                    updated_at=last_event_time,
                )
            )

        await session.commit()
        print("seed done")


async def main() -> None:
    await seed()

    # 汇总验证
    async with SessionFactory() as session:
        for table in ("users", "products", "orders", "order_items", "logistics"):
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            print(f"{table}: {count}")
        events = (
            await session.execute(
                text("SELECT sum(jsonb_array_length(timeline)) FROM logistics")
            )
        ).scalar_one()
        print(f"logistics timeline events (物流记录总数): {events}")


if __name__ == "__main__":
    asyncio.run(main())
