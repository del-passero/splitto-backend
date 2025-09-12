# src/schemas/transaction.py
# -----------------------------------------------------------------------------
# СХЕМЫ Pydantic: Transaction
# -----------------------------------------------------------------------------
# Цели:
#   • Типобезопасные входные/выходные модели для FastAPI.
#   • Без жёсткой фиксации “2 знаков” — точность валидируем/квантуем по Currency.decimals
#     в сервисном слое (роутер/сервис), а не в схемах.
#   • Поле валюты переименовано в currency_code (ISO-4217, 3 буквы).
# -----------------------------------------------------------------------------

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, validator, condecimal

from src.schemas.transaction_share import TransactionShareOut, TransactionShareBase
from src.schemas.expense_category import ExpenseCategoryForTxOut

# Денежное поле без фиксированного количества знаков после запятой.
# Масштаб округления определяется Currency.decimals на уровне сервиса.
Money = condecimal(max_digits=18, ge=0)


class TransactionBase(BaseModel):
    group_id: int
    type: Literal["expense", "transfer"]
    amount: Money

    date: datetime = Field(default_factory=datetime.utcnow)
    comment: Optional[str] = None

    category_id: Optional[int] = None
    paid_by: Optional[int] = None

    split_type: Optional[Literal["equal", "shares", "custom"]] = None

    transfer_from: Optional[int] = None
    transfer_to: Optional[List[int]] = None

    # Валюта транзакции (может не приходить на create — тогда берём дефолт группы)
    currency_code: Optional[str] = None

    receipt_url: Optional[str] = None
    receipt_data: Optional[dict] = None

    @validator("currency_code")
    def _normalize_currency_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = str(v).strip()
        if v == "":
            return None
        v = v.upper()
        if len(v) != 3:
            raise ValueError("Код валюты должен содержать 3 символа (ISO 4217)")
        return v


class TransactionCreate(TransactionBase):
    shares: Optional[List[TransactionShareBase]] = None

    @validator("shares", always=True)
    def _require_shares_when_needed(cls, shares: Optional[List[TransactionShareBase]], values):
        """
        Валидация наличия списка долей при split_type='custom'/'shares'.
        ВАЖНО: проверку ТОЧНОЙ суммы долей против amount и округление
        выполняем на уровне сервиса с учётом Currency.decimals.
        """
        split_type = values.get("split_type")
        if split_type in ("custom", "shares") and (not shares or len(shares) == 0):
            raise ValueError("Для split_type='custom' или 'shares' необходимо передать список долей 'shares'")
        return shares


class TransactionUpdate(TransactionBase):
    """
    Обновление транзакции:
      • Если currency_code НЕ прислан — валюту транзакции НЕ меняем.
      • Проверки сумм долей — на сервисном уровне с учётом decimals.
    """
    shares: Optional[List[TransactionShareBase]] = None


class TransactionOut(TransactionBase):
    id: int
    created_by: int
    created_at: datetime
    updated_at: datetime

    category: Optional[ExpenseCategoryForTxOut] = None
    shares: List[TransactionShareOut] = Field(default_factory=list)

    class Config:
        from_attributes = True
