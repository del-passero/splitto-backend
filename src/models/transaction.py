# src/models/transaction.py
# -----------------------------------------------------------------------------
# МОДЕЛЬ: Transaction (SQLAlchemy)
# -----------------------------------------------------------------------------

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    Numeric,
    DateTime,
    Boolean,
    JSON,
    Index,
    text,
)
from sqlalchemy.orm import relationship

from src.db import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)

    group_id = Column(
        Integer,
        ForeignKey("groups.id"),
        nullable=False,
        comment="ID группы, к которой относится транзакция",
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        comment="Пользователь, создавший транзакцию",
    )

    type = Column(
        String,
        nullable=False,
        comment="'expense' — расход, 'transfer' — перевод (транш)",
    )

    amount = Column(
        Numeric(18, 6),
        nullable=False,
        comment="Сумма транзакции (NUMERIC(18,6))",
    )

    currency_code = Column(
        String(3),
        nullable=True,
        comment="Код валюты ISO-4217 (напр., 'USD'). Фиксируется на транзакции.",
    )

    date = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="Дата расхода/перевода",
    )

    comment = Column(
        String,
        nullable=True,
        comment="Комментарий/описание",
    )

    category_id = Column(
        Integer,
        ForeignKey("expense_categories.id"),
        nullable=True,
        comment="Категория расхода (только для type='expense')",
    )

    paid_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        comment="Кто оплатил (для расходов)",
    )

    split_type = Column(
        String,
        nullable=True,
        comment="Тип деления ('equal', 'shares', 'custom')",
    )

    transfer_from = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        comment="Отправитель денег (для переводов)",
    )

    transfer_to = Column(
        JSON,
        nullable=True,
        comment="Список получателей (user_id) для переводов; JSON-массив",
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="Когда создана запись",
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="Когда последний раз изменяли",
    )

    is_deleted = Column(
        Boolean,
        default=False,
        comment="Soft-delete флаг",
    )

    receipt_url = Column(
        String,
        nullable=True,
        comment="Ссылка на файл чека (если прикреплён)",
    )

    receipt_data = Column(
        JSON,
        nullable=True,
        comment="Результат OCR/парсинга чека (если есть)",
    )

    __table_args__ = (
        Index("ix_tx_group_date", "group_id", "date"),
        Index(
            "ix_tx_group_currency_active",
            "group_id",
            "currency_code",
            postgresql_where=text("is_deleted = false"),
        ),
    )

    group = relationship("Group", backref="transactions", lazy="joined")
    author = relationship("User", foreign_keys=[created_by], lazy="joined")
    payer = relationship("User", foreign_keys=[paid_by], lazy="joined")
    transfer_from_user = relationship("User", foreign_keys=[transfer_from], lazy="joined")
    category = relationship("ExpenseCategory", backref="transactions", lazy="joined")

    shares = relationship(
        "TransactionShare",
        back_populates="transaction",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
