"""
groups lifecycle: status/archived_at/deleted_at/end_date/auto_archive/default_currency_code + indexes
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# ВАЖНО: эта ревизия должна идти после 20250912_mc_ct
revision: str = "20250920_groups_lifecycle"
down_revision: str | None = "20250912_mc_ct"
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
    cols = _col_names(bind, "groups")
    idxs = _idx_names(bind, "groups")

    # 0) ENUM group_status (active|archived)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'group_status') THEN
                CREATE TYPE group_status AS ENUM ('active','archived');
            END IF;
        END$$;
    """)

    # 1) status
    if "status" not in cols:
        op.add_column(
            "groups",
            sa.Column(
                "status",
                sa.Enum("active", "archived", name="group_status"),
                nullable=False,
                server_default=sa.text("'active'"),
                comment="Статус группы: active|archived",
            ),
        )

    # 2) archived_at
    if "archived_at" not in cols:
        op.add_column(
            "groups",
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True, comment="Когда перевели в archived (UTC)"),
        )

    # 3) deleted_at
    if "deleted_at" not in cols:
        op.add_column(
            "groups",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, comment="Soft-delete метка"),
        )

    # 4) end_date
    if "end_date" not in cols:
        op.add_column(
            "groups",
            sa.Column("end_date", sa.Date(), nullable=True, comment="Дата окончания события/поездки"),
        )

    # 5) auto_archive
    if "auto_archive" not in cols:
        op.add_column(
            "groups",
            sa.Column(
                "auto_archive",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
                comment="Автоархив после end_date (если нет долгов)",
            ),
        )

    # 6) default_currency_code
    if "default_currency_code" not in cols:
        op.add_column(
            "groups",
            sa.Column(
                "default_currency_code",
                sa.String(length=3),
                nullable=False,
                server_default=sa.text("'USD'"),
                comment="Дефолтная валюта группы (ISO-4217)",
            ),
        )
        # Бэкофилл на всякий случай
        op.execute("UPDATE groups SET default_currency_code='USD' WHERE default_currency_code IS NULL;")

    # 7) индексы (создаём, если нет)
    if "ix_groups_status" not in idxs:
        op.create_index("ix_groups_status", "groups", ["status"])
    if "ix_groups_deleted_at" not in idxs:
        op.create_index("ix_groups_deleted_at", "groups", ["deleted_at"])
    if "ix_groups_end_date_auto_archive" not in idxs:
        op.create_index("ix_groups_end_date_auto_archive", "groups", ["end_date", "auto_archive"])
    if "ix_groups_default_currency_code" not in idxs:
        op.create_index("ix_groups_default_currency_code", "groups", ["default_currency_code"])


def downgrade() -> None:
    bind = op.get_bind()
    cols = _col_names(bind, "groups")
    idxs = _idx_names(bind, "groups")

    # удаляем индексы (если есть)
    if "ix_groups_default_currency_code" in idxs:
        op.drop_index("ix_groups_default_currency_code", table_name="groups")
    if "ix_groups_end_date_auto_archive" in idxs:
        op.drop_index("ix_groups_end_date_auto_archive", table_name="groups")
    if "ix_groups_deleted_at" in idxs:
        op.drop_index("ix_groups_deleted_at", table_name="groups")
    if "ix_groups_status" in idxs:
        op.drop_index("ix_groups_status", table_name="groups")

    # удаляем столбцы
    if "default_currency_code" in cols:
        op.drop_column("groups", "default_currency_code")
    if "auto_archive" in cols:
        op.drop_column("groups", "auto_archive")
    if "end_date" in cols:
        op.drop_column("groups", "end_date")
    if "deleted_at" in cols:
        op.drop_column("groups", "deleted_at")
    if "archived_at" in cols:
        op.drop_column("groups", "archived_at")
    if "status" in cols:
        op.drop_column("groups", "status")

    # удаляем тип ENUM, если он есть
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'group_status') THEN DROP TYPE group_status; END IF; END$$;")
