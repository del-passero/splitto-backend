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
    # group_id обычно приходит из path /groups/{id}/categories
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
    group_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ExpenseCategoryLocalizedOut(ExpenseCategoryOut):
    # Расширение для локализации (если используете)
    name_ru: Optional[str] = None
    name_en: Optional[str] = None
    name_es: Optional[str] = None
    translations: Optional[Dict[str, str]] = None


class ExpenseCategoryForTxOut(BaseModel):
    """
    Мягкая схема для вложенной категории в TransactionOut:
    НЕ требуем name, чтобы не падать на старых/битых записях.
    """
    id: int
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_income: Optional[bool] = None
    is_archived: Optional[bool] = None
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
    "ExpenseCategoryForTxOut",
)
