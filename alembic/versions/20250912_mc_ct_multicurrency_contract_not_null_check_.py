# alembic/versions/20250912_mc_ct.py
"""
multicurrency contract: NOT NULL/CHECK/FK, drop old currency
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "20250912_mc_ct"
down_revision: str | None = "20250912_mc_bf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0) Защитная проверка — не допускаем NULL перед SET NOT NULL
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM transactions WHERE currency_code IS NULL) THEN
            RAISE EXCEPTION 'Found NULL currency_code in transactions';
          END IF;
        END$$;
    """)

    # 1) NOT NULL
    op.alter_column(
        "transactions",
        "currency_code",
        existing_type=sa.String(length=3),
        nullable=False,
    )

    # 2) CHECK на формат '^[A-Z]{3}$'
    op.create_check_constraint(
        "chk_tx_currency_code_3",
        "transactions",
        sa.text("currency_code ~ '^[A-Z]{3}$'"),
    )

    # 3) FK -> currencies(code)
    op.create_foreign_key(
        "fk_tx_currency",
        source_table="transactions",
        referent_table="currencies",
        local_cols=["currency_code"],
        remote_cols=["code"],
    )

    # 4) Удаляем старую колонку currency, если она ещё есть
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("transactions")]
    if "currency" in cols:
        op.drop_column("transactions", "currency")


def downgrade() -> None:
    # Возвращаем колонку currency (nullable), снимаем ограничения, делаем currency_code nullable.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("transactions")]

    if "currency" not in cols:
        op.add_column("transactions", sa.Column("currency", sa.String(length=3), nullable=True))

    # Снять FK/CHECK (если существуют)
    try:
        op.drop_constraint("fk_tx_currency", "transactions", type_="foreignkey")
    except Exception:
        pass
    try:
        op.drop_constraint("chk_tx_currency_code_3", "transactions", type_="check")
    except Exception:
        pass

    op.alter_column(
        "transactions",
        "currency_code",
        existing_type=sa.String(length=3),
        nullable=True,
    )

    # Заполнить currency из currency_code (по желанию)
    op.execute("""
        UPDATE transactions
        SET currency = currency_code
        WHERE currency IS NULL
          AND currency_code IS NOT NULL
    """)
