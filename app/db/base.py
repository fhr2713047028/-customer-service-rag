"""所有 ORM 模型的公共基类。

后续模块创建商品/订单/物流等模型时都继承 Base，
SQLAlchemy 通过它收集元数据，供建表和 alembic 迁移使用。
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
