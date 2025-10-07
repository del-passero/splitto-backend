"""groups: add last_event_at

Revision ID: 20251007_add_last_event_at
Revises: c400736e1f88
Create Date: 2025-10-07 15:54:18.684446
groups: add last_event_at

<описание: добавляет колонку last_event_at TIMESTAMPTZ NULL + индекс для сортировки>
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20251007_add_last_event_at"
down_revision: Union[str, None] = "c400736e1f88"  # последняя миграция, которую ты показывал
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---- helpers ----
def _col_names(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}

def _index_names(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {ix["name"] for ix in insp.get_indexes(table)}

# ---- upgrade ----
def upgrade() -> None:
    bind = op.get_bind()
    cols = _col_names(bind, "groups")
    if "last_event_at" not in cols:
        op.add_column(
            "groups",
            sa.Column(
                "last_event_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="Дата последнего события или транзакции в группе (UTC)",
            ),
        )

    ix_names = _index_names(bind, "groups")
    if "ix_groups_last_event_at" not in ix_names:
        op.create_index(
            "ix_groups_last_event_at",
            "groups",
            ["last_event_at"],
            unique=False,
        )

# ---- downgrade ----
def downgrade() -> None:
    bind = op.get_bind()

    ix_names = _index_names(bind, "groups")
    if "ix_groups_last_event_at" in ix_names:
        op.drop_index("ix_groups_last_event_at", table_name="groups")

    cols = _col_names(bind, "groups")
    if "last_event_at" in cols:
        op.drop_column("groups", "last_event_at")
