# src/models/transaction.py

from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    Numeric,          # ✅ вместо Float — денежные суммы храним как Numeric(12,2)
    DateTime,
    Boolean,
    JSON,
    Index,            # ✅ индекс для быстрых выборок по группе и дате
)
from sqlalchemy.orm import relationship
from datetime import datetime

from src.db import Base


class Transaction(Base):
    """
    Транзакция — расход или транш в группе.
    Важно: денежные суммы (amount) теперь хранятся как Decimal/Numeric(12,2), чтобы
    исключить плавающие ошибки округления, присущие float.
    """
    __tablename__ = "transactions"

    # --- Основные поля ---
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

    # ✅ БЫЛО: Float → СТАЛО: Numeric(12,2)
    # Денежные суммы нельзя хранить в float из-за двоичной арифметики и ошибок округления.
    amount = Column(
        Numeric(12, 2),
        nullable=False,
        comment="Сумма транзакции",
    )

    date = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="Дата расхода/транша",
    )

    comment = Column(
        String,
        nullable=True,
        comment="Комментарий или описание",
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
        comment="Отправитель денег (только для type='transfer')",
    )

    transfer_to = Column(
        JSON,
        nullable=True,
        comment="Список получателей (user_id), для transfer — один или несколько, JSON-массив",
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="Дата и время создания",
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="Дата и время последнего изменения",
    )

    # ✅ Ограничили длину кода валюты до 3 символов (ISO 4217),
    # сам апстрим/роутер должен приводить к UPPER перед записью
    currency = Column(
        String(3),
        nullable=True,
        comment="Валюта транзакции, по умолчанию RUB",
    )

    is_deleted = Column(
        Boolean,
        default=False,
        comment="Признак soft delete (архивирования)",
    )

    receipt_url = Column(
        String,
        nullable=True,
        comment="Ссылка на файл чека (если прикреплён)",
    )

    receipt_data = Column(
        JSON,
        nullable=True,
        comment="Результат распознавания чека (массив товаров, итог и т.д.)",
    )

    # --- Индексы таблицы ---
    # ✅ Часто листаем транзакции по группе с сортировкой по дате — добавим составной индекс.
    __table_args__ = (
        Index("ix_tx_group_date", "group_id", "date"),
    )

    # --- Связи (ORM relationships) ---
    # Группа (удобно иметь явную связь)
    group = relationship("Group", backref="transactions", lazy="joined")

    # Пользователь-автор (created_by)
    author = relationship("User", foreign_keys=[created_by], lazy="joined")

    # Плательщик для расхода (paid_by)
    payer = relationship("User", foreign_keys=[paid_by], lazy="joined")

    # Отправитель для перевода (transfer_from)
    transfer_from_user = relationship("User", foreign_keys=[transfer_from], lazy="joined")

    # Категория расхода
    category = relationship("ExpenseCategory", backref="transactions", lazy="joined")

    # Доли участников по транзакции
    # Оставляем каскад, чтобы при удалении транзакции удалялись её доли.
    shares = relationship(
        "TransactionShare",
        back_populates="transaction",
        cascade="all, delete-orphan",
        lazy="selectin",  # оптимизация N+1 по сравнению с lazy="joined" в списках
    )
