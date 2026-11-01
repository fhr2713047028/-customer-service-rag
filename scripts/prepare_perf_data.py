"""压测数据准备：预取订单号/物流单号/令牌到 JSON，供 locust 使用。

locust 运行在 gevent 环境，不能在 on_start 里跑 asyncio（协程不会被执行），
因此压测数据在此脚本（正常环境）中提前生成。

用法：
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python -m scripts.prepare_perf_data
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.security import create_access_token
from app.db.session import SessionFactory
from app.models.logistics import Logistics
from app.models.order import Order
from app.models.user import User

OUT = Path("results/perf_data.json")


async def main() -> None:
    async with SessionFactory() as session:
        user = (await session.execute(select(User).where(User.id == 1))).scalar_one_or_none()
        if user is None:
            print("[error] 需要先运行种子数据")
            return
        token = create_access_token(user.id, user.is_admin)
        order_nos = list(
            (
                await session.execute(
                    select(Order.order_no).where(Order.user_id == 1).order_by(Order.id).limit(300)
                )
            ).scalars()
        )
        tracking_nos = list(
            (
                await session.execute(
                    select(Logistics.tracking_no)
                    .join(Order, Logistics.order_id == Order.id)
                    .where(Order.user_id == 1)
                    .limit(100)
                )
            ).scalars()
        )

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"token": token, "order_nos": order_nos, "tracking_nos": tracking_nos},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"压测数据已生成: {OUT}（订单号 {len(order_nos)} 个 / 物流单号 {len(tracking_nos)} 个）")


if __name__ == "__main__":
    asyncio.run(main())
