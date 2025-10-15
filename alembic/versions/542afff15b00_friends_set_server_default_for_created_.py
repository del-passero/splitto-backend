"""friends: set server default for created_at (+updated_at) and backfill nulls

Revision ID: 542afff15b00
Revises: dbe05f5eab3c
Create Date: 2025-10-16 02:47:44.595549

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '542afff15b00'
down_revision: Union[str, None] = 'dbe05f5eab3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1) backfill
    op.execute("UPDATE friends SET created_at = NOW() WHERE created_at IS NULL")
    op.execute("UPDATE friends SET updated_at = NOW() WHERE updated_at IS NULL")

    # 2) server defaults
    op.alter_column(
        "friends",
        "created_at",
        existing_type=sa.DateTime(),
        server_default=sa.text("NOW()"),
        existing_nullable=False,  # если колонка nullable=True — поставьте True
    )
    # updated_at можно тоже выставить default NOW(), чтобы bulk-вставки всегда проходили
    op.alter_column(
        "friends",
        "updated_at",
        existing_type=sa.DateTime(),
        server_default=sa.text("NOW()"),
        existing_nullable=True,  # скорей всего updated_at nullable — оставляем True
    )


def downgrade():
    op.alter_column(
        "friends",
        "created_at",
        existing_type=sa.DateTime(),
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column(
        "friends",
        "updated_at",
        existing_type=sa.DateTime(),
        server_default=None,
        existing_nullable=True,
    )
