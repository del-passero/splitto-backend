# alembic/versions/2025_09_12_multicurrency_expand.py
"""
multicurrency expand: add currency_code, widen to numeric(18,6), partial index
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# Идентификаторы ревизии
revision: str = "2025_09_12_multicurrency_expand"
down_revision: str | None = "2025_08_15_expense_categories_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) transactions.currency_code (NULL на этом шаге)
    op.add_column(
        "transactions",
        sa.Column("currency_code", sa.String(length=3), nullable=True, comment="ISO-4217 код валюты транзакции"),
    )

    # 2) Увеличиваем точность денег до NUMERIC(18,6)
    #    (на Postgres это безопасно; таблица будет переписана — планируй окно)
    op.alter_column("transactions", "amount", type_=sa.Numeric(18, 6), existing_type=sa.Numeric(12, 2), existing_nullable=False)
    op.alter_column("transaction_shares", "amount", type_=sa.Numeric(18, 6), existing_type=sa.Numeric(12, 2), existing_nullable=False)

    # 3) Частичный индекс для быстрых выборок баланса:
    #    CREATE INDEX CONCURRENTLY ix_tx_group_currency_active ON transactions (group_id, currency_code) WHERE is_deleted = false;
    #    Нужен autocommit-блок, т.к. CONCURRENTLY запрещён внутри транзакции.
    ctx = op.get_context()
    if ctx.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.create_index(
                "ix_tx_group_currency_active",
                "transactions",
                ["group_id", "currency_code"],
                postgresql_where=sa.text("is_deleted = false"),
                postgresql_concurrently=True,
            )
    else:
        # На других СУБД — обычный индекс без partial (или пропусти)
        op.create_index("ix_tx_group_currency_active", "transactions", ["group_id", "currency_code"])


def downgrade() -> None:
    # Удаляем индекс (CONCURRENTLY) если PG
    ctx = op.get_context()
    if ctx.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index("ix_tx_group_currency_active", table_name="transactions", postgresql_concurrently=True)
    else:
        op.drop_index("ix_tx_group_currency_active", table_name="transactions")

    # Возвращаем старую точность
    op.alter_column("transaction_shares", "amount", type_=sa.Numeric(12, 2), existing_type=sa.Numeric(18, 6), existing_nullable=False)
    op.alter_column("transactions", "amount", type_=sa.Numeric(12, 2), existing_type=sa.Numeric(18, 6), existing_nullable=False)

    # Удаляем новую колонку
    op.drop_column("transactions", "currency_code")
