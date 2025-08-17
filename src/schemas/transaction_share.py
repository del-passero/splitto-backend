# src/schemas/transaction_share.py

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, condecimal

# Decimal с 2 знаками после запятой (синхронизирован с Numeric(12,2) в БД)
Money = condecimal(max_digits=12, decimal_places=2, ge=0)


class TransactionShareBase(BaseModel):
    user_id: int = Field(..., description="ID участника группы")
    amount: Money = Field(..., description="Сумма доли участника")
    # для split_type='shares'
    shares: Optional[int] = Field(default=None, ge=1, description="Число долей (для split_type='shares')")


class TransactionShareCreate(TransactionShareBase):
    pass


class TransactionShareOut(TransactionShareBase):
    id: int

    class Config:
        from_attributes = True
