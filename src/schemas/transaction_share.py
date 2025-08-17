# src/schemas/transaction_share.py
# Pydantic-схемы долей по транзакции (Base/Create/Out)
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, condecimal

# Точный тип денег: Decimal с 2 знаками после запятой (синхронизирован с Numeric(12,2) в БД)
Money = condecimal(max_digits=12, decimal_places=2, ge=0)


class TransactionShareBase(BaseModel):
    """
    Базовая схема доли по расходу/транзакции.
    """
    user_id: int = Field(..., description="ID участника группы")
    amount: Money = Field(..., description="Сумма доли участника")
    shares: Optional[int] = Field(default=None, ge=1, description="Число долей (для split_type='shares')")


class TransactionShareCreate(TransactionShareBase):
    """
    Схема для создания доли (используется при создании транзакции).
    """
    pass


class TransactionShareOut(TransactionShareBase):
    """
    Схема для отдачи доли на фронт.
    """
    id: int

    class Config:
        # Pydantic v2: позволяем заполнять из ORM-моделей
        from_attributes = True
