# src/models/transaction_share.py
# Модель доли участника в транзакции + уникальность (transaction_id, user_id)

from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    Numeric,           # ✅ вместо Float — точный десятичный тип для денег
    UniqueConstraint,
    Index,             # ✅ индексы для частых выборок
)
from sqlalchemy.orm import relationship

from src.db import Base


class TransactionShare(Base):
    """
    Доля по транзакции — сколько должен конкретный участник по этому расходу.
    Используется для индивидуальных и долевых делений.
    """
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
        comment="Участник группы",
    )

    # ✅ БЫЛО: Float → СТАЛО: Numeric(12,2)
    # Деньги храним в точном десятичном формате, чтобы не ловить ошибки округления float.
    amount = Column(
        Numeric(12, 2),
        nullable=False,
        comment="Сумма, которую должен этот участник",
    )

    # Кол-во долей (если split_type='shares'); может быть None
    shares = Column(Integer, nullable=True, comment="Кол-во долей (если split_type='shares')")

    # --- Уникальность и индексы ---
    # Один пользователь — одна запись доли на транзакцию
    __table_args__ = (
        UniqueConstraint("transaction_id", "user_id", name="uq_tx_shares_tx_user"),
        # ✅ частые выборки по транзакции и по пользователю
        Index("ix_txshare_tx", "transaction_id"),
        Index("ix_txshare_user", "user_id"),
    )

    # --- Связи (ORM relationships) ---
    # Связь с транзакцией: Transaction.shares <-> TransactionShare.transaction
    transaction = relationship("Transaction", back_populates="shares", lazy="joined")

    # Удобная связь на пользователя (для joinedload/selectinload в списках)
    user = relationship("User", lazy="joined")
