"""dashboard: add analytical indexes

Revision ID: 20251007_dashboard_indexes
Revises: 20251007_add_last_event_at
Create Date: 2025-10-07 15:58:39.869059

dashboard: add analytical indexes

<описание: индексы для ускорения аналитических запросов дашборда>
"""
from __future__ import annotations

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20251007_dashboard_indexes"
down_revision: Union[str, None] = "20251007_add_last_event_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_names(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {ix["name"] for ix in insp.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # ---- TRANSACTIONS ----
    ix = _index_names(bind, "transactions")
    if "ix_tx_date" not in ix:
        op.create_index("ix_tx_date", "transactions", ["date"], unique=False)
    if "ix_tx_currency_date" not in ix:
        op.create_index("ix_tx_currency_date", "transactions", ["currency_code", "date"], unique=False)
    if "ix_tx_category_date" not in ix:
        op.create_index("ix_tx_category_date", "transactions", ["category_id", "date"], unique=False)
    if "ix_tx_group_date" not in ix:
        op.create_index("ix_tx_group_date", "transactions", ["group_id", "date"], unique=False)
    if "ix_tx_author_date" not in ix:
        op.create_index("ix_tx_author_date", "transactions", ["created_by", "date"], unique=False)

    # ---- TRANSACTION_SHARES ----
    ix = _index_names(bind, "transaction_shares")
    if "ix_shares_user_tx" not in ix:
        op.create_index("ix_shares_user_tx", "transaction_shares", ["user_id", "transaction_id"], unique=False)

    # ---- EVENTS ----
    ix = _index_names(bind, "events")
    if "ix_events_created_at" not in ix:
        op.create_index("ix_events_created_at", "events", ["created_at"], unique=False)
    if "ix_events_type_created_at" not in ix:
        op.create_index("ix_events_type_created_at", "events", ["type", "created_at"], unique=False)
    if "ix_events_group_created_at" not in ix:
        op.create_index("ix_events_group_created_at", "events", ["group_id", "created_at"], unique=False)
    if "ix_events_actor_created_at" not in ix:
        op.create_index("ix_events_actor_created_at", "events", ["actor_id", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    for table, indexes in {
        "transactions": [
            "ix_tx_date",
            "ix_tx_currency_date",
            "ix_tx_category_date",
            "ix_tx_group_date",
            "ix_tx_author_date",
        ],
        "transaction_shares": ["ix_shares_user_tx"],
        "events": [
            "ix_events_created_at",
            "ix_events_type_created_at",
            "ix_events_group_created_at",
            "ix_events_actor_created_at",
        ],
    }.items():
        existing = _index_names(bind, table)
        for ix in indexes:
            if ix in existing:
                op.drop_index(ix, table_name=table)

