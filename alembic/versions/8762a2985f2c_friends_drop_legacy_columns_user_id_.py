"""friends: drop legacy columns user_id/friend_id/hidden

Revision ID: 20251016_friends_cleanup
Revises: 20251016_friends_fk
Create Date: 2025-10-16 12:20:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union, Set
from alembic import op
import sqlalchemy as sa

revision: str = "20251016_friends_cleanup"
down_revision: Union[str, None] = "20251016_friends_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # 1) снять старый unique (если остался)
    uqs: Set[str] = {u["name"] for u in insp.get_unique_constraints("friends")}
    if "_user_friend_uc" in uqs:
        op.drop_constraint("_user_friend_uc", "friends", type_="unique")

    # 2) удалить legacy-колонки, если они существуют
    cols: Set[str] = {c["name"] for c in insp.get_columns("friends")}
    if "hidden" in cols:
        op.drop_column("friends", "hidden")
    if "friend_id" in cols:
        op.drop_column("friends", "friend_id")
    if "user_id" in cols:
        op.drop_column("friends", "user_id")


def downgrade() -> None:
    # Возвращаем поля для формального даунгрейда (без данных)
    op.add_column("friends", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("friends", sa.Column("friend_id", sa.Integer(), nullable=True))
    op.add_column("friends", sa.Column("hidden", sa.Boolean(), nullable=True))
    op.create_unique_constraint("_user_friend_uc", "friends", ["user_id", "friend_id"])
