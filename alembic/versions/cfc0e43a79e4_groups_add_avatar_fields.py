"""groups: add avatar fields

Revision ID: cfc0e43a79e4
Revises: 20250920_gm_soft_delete
Create Date: 2025-09-27 20:24:41.161791

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cfc0e43a79e4"
down_revision: Union[str, None] = "20250920_gm_soft_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_names(bind, table: str):
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _col_names(bind, "groups")

    if "avatar_url" not in cols:
        op.add_column(
            "groups",
            sa.Column(
                "avatar_url",
                sa.String(length=512),
                nullable=True,
                comment="Публичный URL аватара группы",
            ),
        )
    if "avatar_file_id" not in cols:
        op.add_column(
            "groups",
            sa.Column(
                "avatar_file_id",
                sa.String(length=256),
                nullable=True,
                comment="Telegram file_id источника (опц.)",
            ),
        )
    if "avatar_updated_at" not in cols:
        op.add_column(
            "groups",
            sa.Column(
                "avatar_updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="Когда аватар обновлён (UTC)",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = _col_names(bind, "groups")

    if "avatar_updated_at" in cols:
        op.drop_column("groups", "avatar_updated_at")
    if "avatar_file_id" in cols:
        op.drop_column("groups", "avatar_file_id")
    if "avatar_url" in cols:
        op.drop_column("groups", "avatar_url")
