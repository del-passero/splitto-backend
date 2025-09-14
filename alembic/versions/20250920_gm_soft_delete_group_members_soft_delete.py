"""
group_members soft delete: deleted_at + indexes
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "20250920_gm_soft_delete"
down_revision: str | None = "20250920_groups_lifecycle"
branch_labels = None
depends_on = None


def _col_names(bind, table: str):
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def _idx_names(bind, table: str):
    insp = sa.inspect(bind)
    return {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _col_names(bind, "group_members")
    idxs = _idx_names(bind, "group_members")

    # 1) deleted_at
    if "deleted_at" not in cols:
        op.add_column(
            "group_members",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, comment="Soft-delete метка"),
        )

    # 2) индексы под частые выборки
    if "ix_group_members_group_active" not in idxs:
        op.create_index("ix_group_members_group_active", "group_members", ["group_id", "deleted_at"])
    if "ix_group_members_user_active" not in idxs:
        op.create_index("ix_group_members_user_active", "group_members", ["user_id", "deleted_at"])


def downgrade() -> None:
    bind = op.get_bind()
    cols = _col_names(bind, "group_members")
    idxs = _idx_names(bind, "group_members")

    if "ix_group_members_user_active" in idxs:
        op.drop_index("ix_group_members_user_active", table_name="group_members")
    if "ix_group_members_group_active" in idxs:
        op.drop_index("ix_group_members_group_active", table_name="group_members")

    if "deleted_at" in cols:
        op.drop_column("group_members", "deleted_at")
