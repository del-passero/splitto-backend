# src/schemas/expense_category.py
from __future__ import annotations

from typing import Optional, Dict
from datetime import datetime
from pydantic import BaseModel, Field


class ExpenseCategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    icon: Optional[str] = None            # emoji или имя иконки
    color: Optional[str] = None           # HEX или var(--token)
    is_income: Optional[bool] = False     # True — доходы; False — расходы
    is_archived: Optional[bool] = False
    parent_id: Optional[int] = None       # для иерархии, если используете


class ExpenseCategoryCreate(ExpenseCategoryBase):
    # group_id обычно приходит из path /groups/{id}/categories, поэтому здесь не указываем
    pass


class ExpenseCategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_income: Optional[bool] = None
    is_archived: Optional[bool] = None
    parent_id: Optional[int] = None


class ExpenseCategoryOut(ExpenseCategoryBase):
    id: int
    group_id: Optional[int] = None        # если у вас есть привязка к группе
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True  # Pydantic v2: ORM-mode


class ExpenseCategoryLocalizedOut(ExpenseCategoryOut):
    """
    Расширение для локализованной выдачи.
    Поддерживает два возможных подхода в БД:
      1) Отдельные поля name_ru/name_en/name_es
      2) Сериализованная мапа переводов (translations)
    Если каких-то атрибутов в ORM-модели нет — они просто будут None.
    """
    # Вариант с явными колонками:
    name_ru: Optional[str] = None
    name_en: Optional[str] = None
    name_es: Optional[str] = None
    # Вариант с мапой (если храните JSONB и мапите на .translations):
    translations: Optional[Dict[str, str]] = None


# >>> ВАЖНО: "мягкая" версия ТОЛЬКО для встраивания в транзакции <<<
class ExpenseCategoryForTxOut(BaseModel):
    """
    Версия категории для вложения в TransactionOut.
    Здесь name НЕобязателен, чтобы не падать на частично заполненных/устаревших данных.
    """
    id: int
    # name допускаем пустой/None
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_income: Optional[bool] = False
    is_archived: Optional[bool] = False
    parent_id: Optional[int] = None

    group_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


__all__ = (
    "ExpenseCategoryCreate",
    "ExpenseCategoryUpdate",
    "ExpenseCategoryOut",
    "ExpenseCategoryLocalizedOut",
    "ExpenseCategoryForTxOut",   # <-- экспортируем новую схему
)
