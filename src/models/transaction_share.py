# src/models/transaction_share.py
# -----------------------------------------------------------------------------
# МОДЕЛЬ: TransactionShare (SQLAlchemy)
# -----------------------------------------------------------------------------
# Назначение:
#   • Храним долю конкретного участника в транзакции.
#   • Используется для индивидуальных сумм и долевого деления.
#
# Важные решения:
#   • amount → NUMERIC(18,6) — точный десятичный тип для денег.
#   • Уникальность (transaction_id, user_id) — один участник = одна запись доли.
#   • Каскадное удаление при удалении транзакции.
# -----------------------------------------------------------------------------

from __future__ import annotations

from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    Numeric,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from src.db import Base


class TransactionShare(Base):
    __tablename__ = "transaction_shares"

    id = Column(Integer, primary_key=True, index=True)

    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        comment="ID транзакции",
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        comment="ID участника группы",
    )

    # Денежная доля участника (точный десятичный тип)
    amount = Column(
        Numeric(18, 6),
        nullable=False,
        comment="Сумма доли участника (NUMERIC(18,6))",
    )

    # Количество долей (для split_type='shares'); может быть None
    shares = Column(Integer, nullable=True, comment="Количество долей (если split_type='shares')")

    __table_args__ = (
        UniqueConstraint("transaction_id", "user_id", name="uq_tx_shares_tx_user"),
        Index("ix_txshare_tx", "transaction_id"),
        Index("ix_txshare_user", "user_id"),
    )

    # ORM-связи
    transaction = relationship("Transaction", back_populates="shares", lazy="joined")
    user = relationship("User", lazy="joined")
