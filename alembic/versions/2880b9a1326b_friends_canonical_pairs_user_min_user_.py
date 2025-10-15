"""friends: canonical pairs (user_min/user_max) with per-user hidden

Revision ID: 20251015_friends_canonical_pairs
Revises: 20251007_dashboard_indexes
Create Date: 2025-10-15 21:32:00.000000

Описание:
- Добавлены поля user_min/user_max и персональные флаги hidden_by_min/hidden_by_max.
- Данные перенесены из старых user_id/friend_id/hidden.
- Удалены дубликаты (A,B)/(B,A) с сохранением одной строки на пару.
- Добавлены ограничения и индексы.
"""

from __future__ import annotations

from typing import Sequence, Union, Set
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20251015_friends_canonical_pairs"
down_revision: Union[str, None] = "20251007_dashboard_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_names(bind, table: str) -> Set[str]:
    insp = sa.inspect(bind)
    return {ix["name"] for ix in insp.get_indexes(table)}


def _unique_names(bind, table: str) -> Set[str]:
    insp = sa.inspect(bind)
    return {uc["name"] for uc in insp.get_unique_constraints(table)}


def _check_names(bind, table: str) -> Set[str]:
    insp = sa.inspect(bind)
    return {cc["name"] for cc in insp.get_check_constraints(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Новые колонки (временно nullable; boolean с server_default=false для простоты)
    op.add_column("friends", sa.Column("user_min", sa.Integer(), nullable=True))
    op.add_column("friends", sa.Column("user_max", sa.Integer(), nullable=True))
    op.add_column("friends", sa.Column("hidden_by_min", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("friends", sa.Column("hidden_by_max", sa.Boolean(), nullable=False, server_default=sa.false()))

    # 2) Миграция данных из старых полей
    #    Предполагаем PostgreSQL (LEAST/GREATEST доступны). Если кто-то дружит "сам с собой",
    #    такие записи удалим перед установкой CHECK (user_min < user_max).
    op.execute(
        """
        UPDATE friends
        SET
          user_min = LEAST(user_id, friend_id),
          user_max = GREATEST(user_id, friend_id),
          hidden_by_min = CASE WHEN user_id < friend_id THEN COALESCE(hidden, FALSE) ELSE FALSE END,
          hidden_by_max = CASE WHEN friend_id < user_id THEN COALESCE(hidden, FALSE) ELSE FALSE END
        """
    )

    # Удаляем дружбу "сам с собой" на всякий случай
    op.execute("DELETE FROM friends WHERE user_min = user_max")

    # 3) Удаляем дубликаты (оставляем минимальный id на пару)
    op.execute(
        """
        DELETE FROM friends f
        USING (
            SELECT user_min, user_max, MIN(id) AS keep_id
            FROM friends
            GROUP BY user_min, user_max
            HAVING COUNT(*) > 1
        ) d
        WHERE f.user_min = d.user_min
          AND f.user_max = d.user_max
          AND f.id <> d.keep_id
        """
    )

    # 4) NOT NULL + ограничения и индексы
    op.alter_column("friends", "user_min", existing_type=sa.Integer(), nullable=False)
    op.alter_column("friends", "user_max", existing_type=sa.Integer(), nullable=False)

    # Снимаем server_default у hidden_by_* (чтобы не прописывался в DDL навсегда)
    op.alter_column("friends", "hidden_by_min", server_default=None)
    op.alter_column("friends", "hidden_by_max", server_default=None)

    checks = _check_names(bind, "friends")
    if "ck_friend_min_lt_max" not in checks:
        op.create_check_constraint("ck_friend_min_lt_max", "friends", "user_min < user_max")

    uniques = _unique_names(bind, "friends")
    if "uq_friend_pair" not in uniques:
        op.create_unique_constraint("uq_friend_pair", "friends", ["user_min", "user_max"])

    idx = _index_names(bind, "friends")
    if "ix_friends_user_min" not in idx:
        op.create_index("ix_friends_user_min", "friends", ["user_min"], unique=False)
    if "ix_friends_user_max" not in idx:
        op.create_index("ix_friends_user_max", "friends", ["user_max"], unique=False)

    # Примечание:
    # Старое ограничение _user_friend_uc (user_id, friend_id) сохраняем на переходный период.
    # Старые колонки user_id/friend_id/hidden НЕ удаляем — их можно будет дропнуть отдельной миграцией,
    # когда убедимся, что весь код переведён.


def downgrade() -> None:
    bind = op.get_bind()

    # Удаляем индексы (если есть)
    idx = _index_names(bind, "friends")
    if "ix_friends_user_min" in idx:
        op.drop_index("ix_friends_user_min", table_name="friends")
    if "ix_friends_user_max" in idx:
        op.drop_index("ix_friends_user_max", table_name="friends")

    # Снимаем ограничения (если есть)
    checks = _check_names(bind, "friends")
    if "ck_friend_min_lt_max" in checks:
        op.drop_constraint("ck_friend_min_lt_max", "friends", type_="check")

    uniques = _unique_names(bind, "friends")
    if "uq_friend_pair" in uniques:
        op.drop_constraint("uq_friend_pair", "friends", type_="unique")

    # Удаляем новые колонки
    op.drop_column("friends", "hidden_by_max")
    op.drop_column("friends", "hidden_by_min")
    op.drop_column("friends", "user_max")
    op.drop_column("friends", "user_min")
