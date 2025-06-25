from sqlalchemy import Column, Integer, ForeignKey, Float
from sqlalchemy.orm import relationship
from src.db import Base

class TransactionShare(Base):
    """
    Доля по транзакции — сколько должен конкретный участник по этому расходу.
    Используется для индивидуальных и долевых делений.
    """
    __tablename__ = "transaction_shares"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, comment="ID транзакции")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, comment="Участник группы")
    amount = Column(Float, nullable=False, comment="Сумма, которую должен этот участник")
    shares = Column(Integer, nullable=True, comment="Кол-во долей (если split_type='shares')")

    transaction = relationship("Transaction", back_populates="shares")
