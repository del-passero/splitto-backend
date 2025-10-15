"""events: set server default for created_at and backfill nulls

Revision ID: dbe05f5eab3c
Revises: 5e7272e9ae53
Create Date: 2025-10-16 02:46:26.797193

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dbe05f5eab3c'
down_revision: Union[str, None] = '5e7272e9ae53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1) backfill
    op.execute("UPDATE events SET created_at = NOW() WHERE created_at IS NULL")

    # 2) server default now()
    op.alter_column(
        "events",
        "created_at",
        existing_type=sa.DateTime(),
        server_default=sa.text("NOW()"),
        existing_nullable=False,  # если у вас nullable=True — поставьте True
    )


def downgrade():
    # убрать server default (данные не трогаем)
    op.alter_column(
        "events",
        "created_at",
        existing_type=sa.DateTime(),
        server_default=None,
        existing_nullable=False,
    )

