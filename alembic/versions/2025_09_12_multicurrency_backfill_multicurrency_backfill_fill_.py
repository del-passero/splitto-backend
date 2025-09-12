# alembic/versions/20250912_mc_bf.py
"""
multicurrency backfill: fill transactions.currency_code
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "20250912_mc_bf"
down_revision: str | None = "2025_09_12_multicurrency_expand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Заполняем из старого transactions.currency (если есть)
    op.execute("""
        UPDATE transactions
        SET currency_code = UPPER(TRIM(currency))
        WHERE currency_code IS NULL
          AND currency IS NOT NULL
    """)

    # 2) Остатки NULL — из groups.default_currency_code
    op.execute("""
        UPDATE transactions t
        SET currency_code = UPPER(TRIM(g.default_currency_code))
        FROM groups g
        WHERE t.group_id = g.id
          AND t.currency_code IS NULL
    """)

    # 3) Нормализация регистра/пробелов (на всякий)
    op.execute("""
        UPDATE transactions
        SET currency_code = UPPER(TRIM(currency_code))
        WHERE currency_code IS NOT NULL
          AND (currency_code <> UPPER(TRIM(currency_code)))
    """)


def downgrade() -> None:
    # Осознанно ничего не делаем, чтобы не терять заполненные данные.
    pass
