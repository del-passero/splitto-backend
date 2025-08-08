# alembic/versions/2025_08_08_groups_v2_and_refs.py
"""
Groups v2: поля статуса/архива/удаления/валюты; новые таблицы currencies, group_hidden, group_categories;
уникальные индексы на group_members и transaction_shares; чистка дублей перед уникализацией.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ——— Идентификаторы ревизии — поставит Alembic сам (или оставь как есть и поправь руками)
revision: str = "2025_08_08_groups_v2"
down_revision: Union[str, None] = '7b08661241e1'  # <— если у тебя уже есть миграции, укажи предыдущую!
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) ENUM group_status + новые колонки в таблице groups
    group_status_enum = sa.Enum("active", "archived", name="group_status")
    group_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column("groups", sa.Column("status", group_status_enum, nullable=False, server_default="active"))
    op.add_column("groups", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("groups", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("groups", sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column("groups", sa.Column("auto_archive", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("groups", sa.Column("default_currency_code", sa.String(length=3), nullable=False, server_default="RUB"))

    # Убедимся, что у старых групп в колонке валюты стоит RUB (если вдруг NULL)
    op.execute("UPDATE groups SET default_currency_code = 'RUB' WHERE default_currency_code IS NULL;")

    # 2) Таблица currencies (справочник валют)
    op.create_table(
        "currencies",
        sa.Column("code", sa.String(length=3), primary_key=True, comment="Код валюты ISO-4217, напр. 'USD'"),
        sa.Column("numeric_code", sa.SmallInteger(), nullable=False, comment="Числовой код ISO-4217"),
        sa.Column("decimals", sa.SmallInteger(), nullable=False, comment="Кол-во знаков после запятой"),
        sa.Column("symbol", sa.String(length=8), nullable=True, comment="Символ валюты"),
        sa.Column("flag_emoji", sa.String(length=8), nullable=True, comment="Эмодзи флага"),
        sa.Column("display_country", sa.String(length=2), nullable=True, comment="ISO-3166 код региона для отображения"),
        sa.Column("name_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment="Локализованные названия"),
        sa.Column("is_popular", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_currencies_numeric_code", "currencies", ["numeric_code"])
    op.create_index("ix_currencies_is_popular", "currencies", ["is_popular"])
    op.create_index("ix_currencies_is_active", "currencies", ["is_active"])
    op.create_index("ix_currencies_numeric_code", "currencies", ["numeric_code"])

    # 3) Таблица group_hidden (персональное скрытие группы)
    op.create_table(
        "group_hidden",
        sa.Column("group_id", sa.Integer(), nullable=False, comment="ID группы"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="ID пользователя"),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("group_id", "user_id", name="pk_group_hidden"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_group_hidden_user_id", "group_hidden", ["user_id"])

    # 4) Таблица group_categories (белый список категорий для группы)
    op.create_table(
        "group_categories",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("group_id", "category_id", name="pk_group_categories"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["expense_categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_group_categories_group_id", "group_categories", ["group_id"])
    op.create_index("ix_group_categories_category_id", "group_categories", ["category_id"])

    # 5) Чистка дублей перед уникальными ограничениями

    # 5.1 group_members: оставляем одну запись на (group_id, user_id)
    op.execute("""
    DELETE FROM group_members gm
    USING (
      SELECT id
      FROM (
        SELECT id,
               ROW_NUMBER() OVER (PARTITION BY group_id, user_id ORDER BY id) AS rn
        FROM group_members
      ) t
      WHERE t.rn > 1
    ) d
    WHERE gm.id = d.id;
    """)

    # 5.2 transaction_shares: агрегация дублей по (transaction_id, user_id)
    # shares: если все NULL, оставляем NULL; иначе суммируем.
    op.execute("""
    CREATE TEMP TABLE txs_agg AS
    SELECT
      transaction_id,
      user_id,
      COALESCE(SUM(amount), 0) AS amount,
      CASE
        WHEN COUNT(shares) FILTER (WHERE shares IS NOT NULL) = 0 THEN NULL
        ELSE COALESCE(SUM(shares), 0)
      END AS shares
    FROM transaction_shares
    GROUP BY transaction_id, user_id;
    """)
    op.execute("DELETE FROM transaction_shares;")
    op.execute("""
    INSERT INTO transaction_shares (transaction_id, user_id, amount, shares)
    SELECT transaction_id, user_id, amount, shares
    FROM txs_agg;
    """)

    # 6) Уникальные ограничения (простым способом; без CONCURRENTLY)
    op.create_unique_constraint("uq_group_members_group_user", "group_members", ["group_id", "user_id"])
    op.create_unique_constraint("uq_tx_shares_tx_user", "transaction_shares", ["transaction_id", "user_id"])

    # 7) (Необязательно) Приводим FK transaction_shares → transactions к ondelete=CASCADE
    # Имя старого FK может отличаться; защищаемся plpgsql-блоком.
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_type='FOREIGN KEY'
          AND table_name='transaction_shares'
          AND constraint_name='transaction_shares_transaction_id_fkey'
      ) THEN
        ALTER TABLE transaction_shares DROP CONSTRAINT transaction_shares_transaction_id_fkey;
      END IF;
    EXCEPTION WHEN others THEN
      -- не рушим миграцию, если имя было другим
      NULL;
    END$$;
    """)
    op.create_foreign_key(
        constraint_name="transaction_shares_transaction_id_fkey",
        source_table="transaction_shares",
        referent_table="transactions",
        local_cols=["transaction_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Убираем уникальные ограничения
    with op.batch_alter_table("transaction_shares"):
        op.drop_constraint("uq_tx_shares_tx_user", type_="unique")
    with op.batch_alter_table("group_members"):
        op.drop_constraint("uq_group_members_group_user", type_="unique")

    # Откатываем таблицы
    op.drop_index("ix_group_categories_category_id", table_name="group_categories")
    op.drop_index("ix_group_categories_group_id", table_name="group_categories")
    op.drop_table("group_categories")

    op.drop_index("ix_group_hidden_user_id", table_name="group_hidden")
    op.drop_table("group_hidden")

    op.drop_index("ix_currencies_numeric_code", table_name="currencies")
    op.drop_index("ix_currencies_is_active", table_name="currencies")
    op.drop_index("ix_currencies_is_popular", table_name="currencies")
    op.drop_constraint("uq_currencies_numeric_code", "currencies", type_="unique")
    op.drop_table("currencies")

    # Убираем колонки из groups
    with op.batch_alter_table("groups") as b:
        b.drop_column("default_currency_code")
        b.drop_column("auto_archive")
        b.drop_column("end_date")
        b.drop_column("deleted_at")
        b.drop_column("archived_at")
        b.drop_column("status")

    # Удаляем ENUM тип
    group_status_enum = sa.Enum("active", "archived", name="group_status")
    group_status_enum.drop(op.get_bind(), checkfirst=True)
