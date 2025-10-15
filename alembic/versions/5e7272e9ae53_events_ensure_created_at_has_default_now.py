"""events: ensure created_at has default now()

Revision ID: 5e7272e9ae53
Revises: e73e730d69b2
Create Date: 2025-10-16 01:52:20.074462

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5e7272e9ae53"
down_revision = "e73e730d69b2"  # твой текущий head-merge
branch_labels = None
depends_on = None

def upgrade():
    # на всякий — добить null'ы
    op.execute("UPDATE events SET created_at = now() WHERE created_at IS NULL;")
    # чтобы в будущем всегда было значение
    op.alter_column(
        "events",
        "created_at",
        server_default=sa.text("now()"),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )

def downgrade():
    # убираем дефолт (схемно)
    op.alter_column(
        "events",
        "created_at",
        server_default=None,
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )