# alembic/versions/2025_08_15_expense_categories_v2.py
# МИГРАЦИЯ: перевод expense_categories в формат "как у валют".
# - ДОБАВЛЕНО: key (UNIQUE), parent_id (self-FK), name_i18n (JSONB NOT NULL),
#              color (TEXT), is_active (BOOL), created_at/updated_at (timestamptz).
# - УДАЛЕНО: name (строка), т.к. теперь используем name_i18n.
# ПРИМЕЧАНИЕ: таблица была пустой — миграция не делает перенос данных.

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Идентификаторы миграций — подставь свою предыдущую head как down_revision,
# у тебя была '2025_08_15_money_and_indexes'
revision = "2025_08_15_expense_categories_v2"
down_revision = "2025_08_15_money_and_indexes"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    def col_exists(col: str) -> bool:
        return bool(conn.execute(sa.text("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'expense_categories'
              AND column_name = :col
        """), {"col": col}).scalar())

    def idx_exists(name: str) -> bool:
        return bool(conn.execute(sa.text("""
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND indexname = :name
        """), {"name": name}).scalar())

    def constr_exists(name: str) -> bool:
        return bool(conn.execute(sa.text("""
            SELECT 1
            FROM information_schema.table_constraints
            WHERE constraint_schema = current_schema()
              AND table_name = 'expense_categories'
              AND constraint_name = :name
        """), {"name": name}).scalar())

    # --- Колонки (add if not exists) ---
    if not col_exists("key"):
        op.add_column("expense_categories", sa.Column("key", sa.String(length=64), nullable=False))
    if not col_exists("parent_id"):
        op.add_column("expense_categories", sa.Column("parent_id", sa.Integer(), nullable=True))
    if not col_exists("icon"):
        op.add_column("expense_categories", sa.Column("icon", sa.String(), nullable=True))
    if not col_exists("color"):
        op.add_column("expense_categories", sa.Column("color", sa.String(length=7), nullable=True))
    if not col_exists("name_i18n"):
        op.add_column(
            "expense_categories",
            sa.Column("name_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb"))
        )
    if not col_exists("is_active"):
        op.add_column("expense_categories", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    if not col_exists("created_at"):
        op.add_column("expense_categories", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    if not col_exists("updated_at"):
        op.add_column("expense_categories", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))

    # --- Ограничения/индексы (create if not exists) ---
    if not constr_exists("uq_expense_categories_key"):
        op.create_unique_constraint("uq_expense_categories_key", "expense_categories", ["key"])
    if not idx_exists("ix_expense_categories_parent_id"):
        op.create_index("ix_expense_categories_parent_id", "expense_categories", ["parent_id"])
    if not idx_exists("ix_expense_categories_is_active"):
        op.create_index("ix_expense_categories_is_active", "expense_categories", ["is_active"])
    if not constr_exists("fk_expense_categories_parent"):
        op.create_foreign_key(
            "fk_expense_categories_parent",
            "expense_categories",
            "expense_categories",
            ["parent_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # --- Сносим старый name, если вдруг есть ---
    if col_exists("name"):
        with op.batch_alter_table("expense_categories") as batch_op:
            batch_op.drop_column("name")

def downgrade():
    # 1) Вернём name (как NOT NULL или NULL — оставим NULL для совместимости)
    op.add_column("expense_categories", sa.Column("name", sa.String(), nullable=True))

    # 2) Сносим внешние ключи/индексы/уникальные
    try:
        op.drop_constraint("fk_expense_categories_parent", "expense_categories", type_="foreignkey")
    except Exception:
        pass
    try:
        op.drop_index("ix_expense_categories_parent_id", table_name="expense_categories")
    except Exception:
        pass
    try:
        op.drop_index("ix_expense_categories_is_active", table_name="expense_categories")
    except Exception:
        pass
    try:
        op.drop_constraint("uq_expense_categories_key", "expense_categories", type_="unique")
    except Exception:
        pass

    # 3) Удаляем новые столбцы
    for col in ["key", "parent_id", "icon", "color", "name_i18n", "is_active", "created_at", "updated_at"]:
        try:
            op.drop_column("expense_categories", col)
        except Exception:
            pass
