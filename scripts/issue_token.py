"""受控测试身份：给种子用户签发 JWT（v1 的认证入口，api_design.md 第 2 节）。

v1 没有注册/登录接口；令牌由本脚本（服务端）签发，客户端不能自造身份。
用法（项目根目录）：
    python -m scripts.issue_token --user-id 1
    python -m scripts.issue_token --user-id 1 --expire-hours 1
输出：JWT，调用方放入 Authorization: Bearer <token>。
"""
import argparse
import asyncio

from sqlalchemy import select

from app.core.security import create_access_token
from app.db.session import SessionFactory
from app.models.user import User


async def main() -> None:
    parser = argparse.ArgumentParser(description="给种子测试用户签发 JWT")
    parser.add_argument("--user-id", type=int, required=True, help="种子用户 id（1~20）")
    parser.add_argument("--expire-hours", type=int, default=24, help="有效期（小时），默认 24")
    args = parser.parse_args()

    async with SessionFactory() as session:
        user = (
            await session.execute(select(User).where(User.id == args.user_id))
        ).scalar_one_or_none()
        if user is None:
            print(f"[error] user id={args.user_id} not found (run scripts/seed_data.py first)")
            return

        token = create_access_token(
            user.id, user.is_admin, expire_minutes=args.expire_hours * 60
        )
        print(f"user: {user.username} (id={user.id}, is_admin={user.is_admin})")
        print("token:")
        print(token)


if __name__ == "__main__":
    asyncio.run(main())
