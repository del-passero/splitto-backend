"""money to numeric(12,2); currency len=3; tx indexes

- transactions.amount: Float -> Numeric(12,2) c безопасным USING (round)
- transaction_shares.amount: Float -> Numeric(12,2) c USING
- transactions.currency: String -> String(3)
- индекс ix_tx_group_date (group_id, date)
- индексы для transaction_shares: ix_txshare_tx, ix_txshare_user
"""

from alembic import op
import sqlalchemy as sa

# поправь под себя идентификаторы:
revision = "2025_08_15_money_and_indexes"
down_revision = "2025_08_08_groups_v2"  # ← поставь текущую "head" из alembic history
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # 1) Безопасно меняем типы сумм на Numeric(12,2) через USING (для Postgres)
    # Если другой диалект — используем alter_column как есть.
    if dialect_name == "postgresql":
        # transactions.amount
        op.execute("""
            ALTER TABLE transactions
            ALTER COLUMN amount TYPE NUMERIC(12,2)
            USING round((amount)::numeric, 2)
        """)
        # transaction_shares.amount
        op.execute("""
            ALTER TABLE transaction_shares
            ALTER COLUMN amount TYPE NUMERIC(12,2)
            USING round((amount)::numeric, 2)
        """)
    else:
        # На прочих диалектах будет обычный alter (если это не поддерживается — адаптируй под СУБД)
        op.alter_column(
            "transactions", "amount",
            type_=sa.Numeric(12, 2),
            existing_type=sa.Float(asdecimal=False),
            existing_nullable=False,
        )
        op.alter_column(
            "transaction_shares", "amount",
            type_=sa.Numeric(12, 2),
            existing_type=sa.Float(asdecimal=False),
            existing_nullable=False,
        )

    # 2) Ограничиваем длину кода валюты до 3 символов
    op.alter_column(
        "transactions", "currency",
        type_=sa.String(length=3),
        existing_type=sa.String(),
        existing_nullable=True,
    )

    # 3) Индекс на (group_id, date) для быстрых списков
    op.create_index(
        "ix_tx_group_date",
        "transactions",
        ["group_id", "date"],
        unique=False,
    )

    # 4) Индексы для частых выборок долей: по транзакции и по пользователю
    # Если индексы уже созданы в других ревизиях, эти строки можно удалить.
    op.create_index("ix_txshare_tx", "transaction_shares", ["transaction_id"], unique=False)
    op.create_index("ix_txshare_user", "transaction_shares", ["user_id"], unique=False)


def downgrade():
    # Откатываем индексы
    op.drop_index("ix_txshare_user", table_name="transaction_shares")
    op.drop_index("ix_txshare_tx", table_name="transaction_shares")
    op.drop_index("ix_tx_group_date", table_name="transactions")

    # Возвращаем длину currency обратно в String (без ограничения)
    op.alter_column(
        "transactions", "currency",
        type_=sa.String(),
        existing_type=sa.String(length=3),
        existing_nullable=True,
    )

    # Возвращаем amount обратно в Float (если потребуется)
    op.alter_column(
        "transaction_shares", "amount",
        type_=sa.Float(asdecimal=False),
        existing_type=sa.Numeric(12, 2),
        existing_nullable=False,
    )
    op.alter_column(
        "transactions", "amount",
        type_=sa.Float(asdecimal=False),
        existing_type=sa.Numeric(12, 2),
        existing_nullable=False,
    )
