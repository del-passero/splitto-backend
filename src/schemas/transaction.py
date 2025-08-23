# src/schemas/transaction.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, validator, condecimal

from src.schemas.transaction_share import TransactionShareOut, TransactionShareBase
from src.schemas.expense_category import ExpenseCategoryForTxOut

Money = condecimal(max_digits=12, decimal_places=2, ge=0)

def q2(x: Decimal) -> Decimal:
  return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

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

  currency: Optional[str] = None

  receipt_url: Optional[str] = None
  receipt_data: Optional[dict] = None

  @validator("currency")
  def _normalize_currency(cls, v: Optional[str]) -> Optional[str]:
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
  def validate_shares_sum(cls, shares: Optional[List[TransactionShareBase]], values):
    split_type = values.get("split_type")
    amount = values.get("amount")

    if split_type in ("custom", "shares"):
      if not shares or len(shares) == 0:
        raise ValueError("Для split_type='custom' или 'shares' обязательно передать список долей 'shares'")

      total = Decimal("0.00")
      for s in shares:
        total += Decimal(str(s.amount))
      total = q2(total)

      if amount is None:
        raise ValueError("Поле 'amount' обязательно для валидации суммы долей")

      total_amount = q2(Decimal(str(amount)))
      if total != total_amount:
        raise ValueError(f"Сумма всех долей ({total}) не совпадает с общей суммой транзакции ({total_amount})")

    return shares

class TransactionUpdate(TransactionBase):
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
