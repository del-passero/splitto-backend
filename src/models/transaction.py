from sqlalchemy import Column, Integer, String, ForeignKey, Float, DateTime, Boolean, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from src.db import Base

class Transaction(Base):
    """
    Транзакция — расход или транш в группе.
    """
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, comment="ID группы, к которой относится транзакция")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, comment="Пользователь, создавший транзакцию")
    type = Column(String, nullable=False, comment="'expense' — расход, 'transfer' — перевод (транш)")
    amount = Column(Float, nullable=False, comment="Сумма транзакции")
    date = Column(DateTime, nullable=False, default=datetime.utcnow, comment="Дата расхода/транша")
    comment = Column(String, nullable=True, comment="Комментарий или описание")
    category_id = Column(Integer, ForeignKey("expense_categories.id"), nullable=True, comment="Категория расхода (только для type='expense')")
    paid_by = Column(Integer, ForeignKey("users.id"), nullable=True, comment="Кто оплатил (для расходов)")
    split_type = Column(String, nullable=True, comment="Тип деления ('equal', 'shares', 'custom')")
    transfer_from = Column(Integer, ForeignKey("users.id"), nullable=True, comment="Отправитель денег (только для type='transfer')")
    transfer_to = Column(JSON, nullable=True, comment="Список получателей (user_id), для transfer — один или несколько, JSON-массив")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="Дата и время создания")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="Дата и время последнего изменения")
    currency = Column(String, nullable=True, comment="Валюта транзакции, по умолчанию RUB")
    is_deleted = Column(Boolean, default=False, comment="Признак soft delete (архивирования)")
    receipt_url = Column(String, nullable=True, comment="Ссылка на файл чека (если прикреплён)")
    receipt_data = Column(JSON, nullable=True, comment="Результат распознавания чека (массив товаров, итог и т.д.)")

    # Внешние ключи (relationships)
    category = relationship("ExpenseCategory", backref="transactions", lazy="joined")
    shares = relationship("TransactionShare", back_populates="transaction", cascade="all, delete-orphan")
