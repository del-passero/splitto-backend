"""friends: add FKs for user_min/user_max

Revision ID: 20251016_friends_fk
Revises: 20251015_friends_canonical_pairs
Create Date: 2025-10-16 10:05:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20251016_friends_fk"
down_revision: Union[str, None] = "20251015_friends_canonical_pairs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def _fk_names(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    fks = insp.get_foreign_keys(table)
    # Некоторые драйверы могут возвращать None в name — фильтруем
    return {fk.get("name") for fk in fks if fk.get("name")}

def upgrade() -> None:
    bind = op.get_bind()
    existing = _fk_names(bind, "friends")

    if "fk_friends_user_min_users" not in existing:
        op.create_foreign_key(
            "fk_friends_user_min_users",
            "friends", "users",
            ["user_min"], ["id"],
            ondelete="CASCADE",
        )
    # Если уже существует, тихо пропускаем

    existing = _fk_names(bind, "friends")  # перечитаем на всякий случай
    if "fk_friends_user_max_users" not in existing:
        op.create_foreign_key(
            "fk_friends_user_max_users",
            "friends", "users",
            ["user_max"], ["id"],
            ondelete="CASCADE",
        )

def downgrade() -> None:
    bind = op.get_bind()
    existing = _fk_names(bind, "friends")

    if "fk_friends_user_min_users" in existing:
        op.drop_constraint("fk_friends_user_min_users", "friends", type_="foreignkey")

    existing = _fk_names(bind, "friends")
    if "fk_friends_user_max_users" in existing:
        op.drop_constraint("fk_friends_user_max_users", "friends", type_="foreignkey")
