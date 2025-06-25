# src/schemas/transaction.py

from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime
from src.schemas.transaction_share import TransactionShareOut
from src.schemas.expense_category import ExpenseCategoryOut
from src.schemas.transaction_share import TransactionShareBase

class TransactionBase(BaseModel):
    """
    Базовая схема транзакции (общие поля, без id и created_by).
    """
    group_id: int
    type: str  # 'expense' или 'transfer'
    amount: float
    date: datetime = Field(default_factory=datetime.utcnow)
    comment: Optional[str] = None
    category_id: Optional[int] = None
    paid_by: Optional[int] = None
    split_type: Optional[str] = None
    transfer_from: Optional[int] = None
    transfer_to: Optional[List[int]] = None  # Один или несколько получателей (для transfer)
    currency: Optional[str] = None
    receipt_url: Optional[str] = None
    receipt_data: Optional[dict] = None  # Структура распознанного чека (опционально)

class TransactionCreate(TransactionBase):
    """
    Схема для создания транзакции через API.
    created_by не передаётся с фронта — он вычисляется на backend.
    """
    shares: Optional[List[TransactionShareBase]] = None  # Список долей (для split_type='custom'/'shares')

    @validator('shares', always=True)
    def validate_shares(cls, shares, values):
        """
        Валидация суммы долей (если указаны).
        """
        split_type = values.get('split_type')
        amount = values.get('amount')
        if split_type in ("custom", "shares") and shares:
            total = sum(s.amount for s in shares)
            if amount is not None and abs(total - amount) > 1e-2:
                raise ValueError(f"Сумма всех долей ({total}) не совпадает с общей суммой транзакции ({amount})")
        return shares

class TransactionOut(TransactionBase):
    """
    Схема для вывода транзакции наружу (на фронт).
    Содержит все связанные данные: id, категории, доли, пользователей и т.д.
    """
    id: int
    created_by: int
    created_at: datetime
    updated_at: datetime
    category: Optional[ExpenseCategoryOut] = None  # Данные категории, если есть
    shares: List[TransactionShareOut] = []         # Список долей (для split_type='custom'/'shares')

    class Config:
        from_attributes = True
