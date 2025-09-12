# src/schemas/transaction_share.py
# -----------------------------------------------------------------------------
# СХЕМЫ Pydantic: TransactionShare (доли участников)
# -----------------------------------------------------------------------------
# Цели:
#   • Не фиксируем число знаков после запятой — масштаб даёт валюта транзакции.
#   • На уровне сервиса сверяем сумму долей с общей суммой (Currency.decimals).
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, condecimal

# Денежное поле без фиксированного decimal_places
Money = condecimal(max_digits=18, ge=0)


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
