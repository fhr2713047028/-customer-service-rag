"""API 冒烟脚本：对运行中的服务做端到端自动验证。

用法（先启动服务，再跑本脚本）：
    uvicorn app.main:app --port 8000
    python -m scripts.smoke_api --base-url http://127.0.0.1:8000

脚本行为：
- 从数据库读取 user 1/2 的订单号与物流单号（只读查询）；
- 用真实 JWT（复用 issue_token 的签发逻辑）调用全部接口；
- 逐项打印 PASS/FAIL 与"实际 vs 预期"对比；
- 全部通过退出码 0，任一失败退出码 1（可直接接 CI）。

覆盖：健康/就绪探针、商品（详情/关键词/404/422）、
订单（401/列表/详情脱敏/他人404）、物流（本人/他人404）。
"""
import argparse
import asyncio

import httpx
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.session import SessionFactory
from app.models.logistics import Logistics
from app.models.order import Order
from app.models.user import User

HTTP_OK = {"code": 0}


async def _load_fixture() -> tuple:
    """从种子数据取 user 1/2 及其订单号、物流单号。"""
    async with SessionFactory() as session:
        user1 = (await session.execute(select(User).where(User.id == 1))).scalar_one_or_none()
        user2 = (await session.execute(select(User).where(User.id == 2))).scalar_one_or_none()
        order_no = (
            await session.execute(
                select(Order.order_no).where(Order.user_id == 1).order_by(Order.id)
            )
        ).scalars().first()
        tracking = (
            await session.execute(
                select(Logistics.tracking_no)
                .join(Order, Logistics.order_id == Order.id)
                .where(Order.user_id == 1)
                .order_by(Logistics.id)
            )
        ).scalars().first()
    return user1, user2, order_no, tracking


async def run_checks(base_url: str) -> int:
    user1, user2, order_no, tracking = await _load_fixture()
    if user1 is None or order_no is None or tracking is None:
        print("[error] 需要先运行种子数据：python -m scripts.seed_data")
        return 1

    token1 = create_access_token(user1.id, user1.is_admin)
    token2 = create_access_token(user2.id, user2.is_admin) if user2 else "invalid.token.for.test"
    h1 = {"Authorization": f"Bearer {token1}"}
    h2 = {"Authorization": f"Bearer {token2}"}

    results: list[tuple[str, bool, str, str]] = []

    async def check(name, resp, expected_status, expected_code=None, extra=None):
        body = {}
        try:
            body = resp.json()
        except Exception:
            pass
        ok = resp.status_code == expected_status
        if ok and expected_code is not None:
            ok = body.get("code") == expected_code
        if ok and extra is not None:
            ok = extra(body)
        actual = f"HTTP {resp.status_code}" + (f" code={body.get('code')}" if "code" in body else "")
        expected = f"HTTP {expected_status}" + (
            f" code={expected_code}" if expected_code is not None else ""
        )
        results.append((name, ok, actual, expected))

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        # 系统与数据库连通性
        await check("健康探针 /healthz", await client.get("/healthz"), 200)
        await check("就绪探针 /readyz（数据库连通）", await client.get("/readyz"), 200)
        # 商品（公开）
        await check("商品详情", await client.get("/api/v1/products/1"), 200, 0)
        await check(
            "商品关键词搜索（命中≥1）",
            await client.get("/api/v1/products", params={"keyword": "耳机"}),
            200, 0, lambda b: b["data"]["total"] >= 1,
        )
        await check("商品不存在 → 404/20002", await client.get("/api/v1/products/999999999"), 404, 20002)
        await check("参数校验 page_size=101 → 422", await client.get("/api/v1/products", params={"page_size": 101}), 422)
        # 订单（认证 + 归属）
        await check("订单列表 无令牌 → 401/10001", await client.get("/api/v1/orders"), 401, 10001)
        await check("订单列表 本人", await client.get("/api/v1/orders", headers=h1), 200, 0)
        await check(
            "订单详情 本人 + 脱敏",
            await client.get(f"/api/v1/orders/{order_no}", headers=h1),
            200, 0, lambda b: "****" in (b["data"]["receiver_phone"] or ""),
        )
        await check("订单详情 他人 → 404/20001", await client.get(f"/api/v1/orders/{order_no}", headers=h2), 404, 20001)
        # 物流（认证 + 归属）
        await check("物流 本人", await client.get(f"/api/v1/logistics/{tracking}", headers=h1), 200, 0)
        await check("物流 他人 → 404/20001", await client.get(f"/api/v1/logistics/{tracking}", headers=h2), 404, 20001)

    failed = 0
    print(f"{'检查项':<26} {'结果':<6} {'实际':<22} 预期")
    print("-" * 80)
    for name, ok, actual, expected in results:
        print(f"{name:<26} {'PASS' if ok else 'FAIL':<6} {actual:<22} {expected}")
        if not ok:
            failed += 1
    print("-" * 80)
    print(f"总计 {len(results)} 项，通过 {len(results) - failed}，失败 {failed}")
    return 1 if failed else 0


async def main() -> None:
    parser = argparse.ArgumentParser(description="API 端到端冒烟验证")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    exit_code = await run_checks(args.base_url)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
