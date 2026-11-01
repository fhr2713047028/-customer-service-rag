"""add metadata to knowledge_chunks

Revision ID: 0e6e5b0f48c2
Revises: 79330a6f94ab
Create Date: 2026-10-31 13:49:22.774130

人工调整说明（autogenerate 假 diff 清理）：
autogenerate 同时生成了 3 处变更，其中 2 处是假 diff，已删除：
- "change index ix_orders_user_id_created_at（DESC→ASC）"：数据库里的
  DESC 索引是迁移 #1 手工指定的正确形态；本次已在模型中用
  text("created_at DESC") 精确声明，模型与数据库一致；
- "remove index idx_products_name_trgm"：该 trigram 索引同样已在模型中
  用 postgresql_using/ops 精确声明；
本迁移只保留真实变更：knowledge_chunks 新增 metadata 列。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0e6e5b0f48c2'
down_revision: Union[str, Sequence[str], None] = '79330a6f94ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'knowledge_chunks',
        sa.Column(
            'metadata',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('knowledge_chunks', 'metadata')
