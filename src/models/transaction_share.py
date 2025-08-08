# src/models/transaction_share.py
# Модель доли участника в транзакции + уникальность (transaction_id, user_id)

from sqlalchemy import Column, Integer, ForeignKey, Float, UniqueConstraint
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
    amount = Column(Float, nullable=False, comment="Сумма, которую должен этот участник")
    shares = Column(Integer, nullable=True, comment="Кол-во долей (если split_type='shares')")

    # Один пользователь — одна запись доли на транзакцию
    __table_args__ = (
        UniqueConstraint("transaction_id", "user_id", name="uq_tx_shares_tx_user"),
    )

    # Связи (как у тебя): Transaction.shares <-> TransactionShare.transaction
    transaction = relationship("Transaction", back_populates="shares")
