"""events: idempotency_key, transaction_id, target index

Revision ID: 20251016_events_enhancements
Revises: 20251016_friends_fk
Create Date: 2025-10-16 14:05:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union, Set
from alembic import op
import sqlalchemy as sa

revision: str = "20251016_events_enhancements"
down_revision: Union[str, None] = "20251016_friends_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> Set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def _index_names(bind, table: str) -> Set[str]:
    insp = sa.inspect(bind)
    return {ix["name"] for ix in insp.get_indexes(table)}


def _unique_names(bind, table: str) -> Set[str]:
    insp = sa.inspect(bind)
    return {u["name"] for u in insp.get_unique_constraints(table)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _columns(bind, "events")

    # 1) idempotency_key (для защиты от дублей логов)
    if "idempotency_key" not in cols:
        op.add_column("events", sa.Column("idempotency_key", sa.String(length=64), nullable=True))

    uqs = _unique_names(bind, "events")
    if "uq_events_idempotency_key" not in uqs:
        # В Postgres UNIQUE допускает несколько NULL — то, что нужно.
        op.create_unique_constraint("uq_events_idempotency_key", "events", ["idempotency_key"])

    # 2) transaction_id (опциональная связка события с транзакцией)
    if "transaction_id" not in cols:
        op.add_column("events", sa.Column("transaction_id", sa.Integer(), nullable=True))
        # FK специально НЕ ставим, чтобы не удалять события при удалении транзакции.
        # Если захочешь FK с ON DELETE SET NULL — сделаем отдельной ревизией.

    # 3) индексы для быстрых выборок
    idx = _index_names(bind, "events")
    if "ix_events_target_created_at" not in idx:
        op.create_index("ix_events_target_created_at", "events", ["target_user_id", "created_at"], unique=False)
    if "ix_events_tx_created_at" not in idx and "transaction_id" in _columns(bind, "events"):
        op.create_index("ix_events_tx_created_at", "events", ["transaction_id", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    idx = _index_names(bind, "events")
    if "ix_events_tx_created_at" in idx:
        op.drop_index("ix_events_tx_created_at", table_name="events")
    if "ix_events_target_created_at" in idx:
        op.drop_index("ix_events_target_created_at", table_name="events")

    uqs = _unique_names(bind, "events")
    if "uq_events_idempotency_key" in uqs:
        op.drop_constraint("uq_events_idempotency_key", "events", type_="unique")

    cols = _columns(bind, "events")
    if "transaction_id" in cols:
        op.drop_column("events", "transaction_id")
    if "idempotency_key" in cols:
        op.drop_column("events", "idempotency_key")
