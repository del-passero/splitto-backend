# src/schemas/transaction.py

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Literal

from datetime import datetime
from pydantic import BaseModel, Field, validator, condecimal

from src.schemas.transaction_share import TransactionShareOut, TransactionShareBase
# ВАЖНО: используем "мягкую" схему категории ТОЛЬКО для TransactionOut
from src.schemas.expense_category import ExpenseCategoryForTxOut


# Точный тип для денег: 0.00 … 9999999999.99 (12 знаков всего, 2 после запятой)
Money = condecimal(max_digits=12, decimal_places=2, ge=0)


def q2(x: Decimal) -> Decimal:
    """Округление до 2 знаков банковским способом."""
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class TransactionBase(BaseModel):
    """
    Базовая схема транзакции (общие поля, без id и created_by).
    """
    group_id: int
    # Было: type: str → стало жёстко ограниченное множество значений
    type: Literal["expense", "transfer"]  # 'expense' — расход, 'transfer' — перевод

    # Было: float → стало Decimal (Money) для точных денежных расчётов
    amount: Money

    date: datetime = Field(default_factory=datetime.utcnow)
    comment: Optional[str] = None

    # Категория применима только к расходам; валидируем логику в роутере
    category_id: Optional[int] = None

    # Для расходов — кто платил; проверяем в роутере, что заполнено при type='expense'
    paid_by: Optional[int] = None

    # Было: str → стало ограниченное множество (или None)
    split_type: Optional[Literal["equal", "shares", "custom"]] = None

    # Для переводов
    transfer_from: Optional[int] = None
    transfer_to: Optional[List[int]] = None  # Один или несколько получателей (для transfer)

    # Валюта: нормализуем к UPPER и длине 3 символа (ISO 4217)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)

    # Чек — как и прежде
    receipt_url: Optional[str] = None
    receipt_data: Optional[dict] = None  # Структура распознанного чека (опционально)

    @validator("currency")
    def _normalize_currency(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip().upper()
        if len(v) != 3:
            raise ValueError("Код валюты должен содержать 3 символа (ISO 4217)")
        return v


class TransactionCreate(TransactionBase):
    """
    Схема для создания транзакции через API.
    created_by не передаётся с фронта — он вычисляется на backend.
    """
    # Было: Optional[List[TransactionShareBase]] = None
    # Оставляем Optional, но валидируем сумму долей при split_type in {'custom','shares'}
    shares: Optional[List[TransactionShareBase]] = None

    @validator("shares", always=True)
    def validate_shares_sum(cls, shares: Optional[List[TransactionShareBase]], values):
        """
        Валидация суммы долей (если указаны) — сравниваем с amount как Decimal с округлением до 2 знаков.
        """
        split_type = values.get("split_type")
        amount = values.get("amount")

        # Если деление 'custom' или 'shares', то должны быть доли и их сумма == amount (с точностью 0.01)
        if split_type in ("custom", "shares"):
            if not shares or len(shares) == 0:
                raise ValueError("Для split_type='custom' или 'shares' обязательно передать список долей 'shares'")

            # Суммируем как Decimal с квантованием
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


class TransactionOut(TransactionBase):
    """
    Схема для вывода транзакции наружу (на фронт).
    Содержит все связанные данные: id, категории, доли, пользователей и т.д.
    """
    id: int
    created_by: int
    created_at: datetime
    updated_at: datetime

    # Вложенная категория — используем "мягкую" версию
    category: Optional[ExpenseCategoryForTxOut] = None

    # Было: shares: List[TransactionShareOut] = []
    # Стало: безопасный дефолт через default_factory (чтобы не было шаринга одного списка между инстансами)
    shares: List[TransactionShareOut] = Field(default_factory=list)

    class Config:
        # как в твоём проекте: работаем с ORM-моделями
        from_attributes = True
