# src/schemas/group_category.py
# СХЕМЫ: «белый список» категорий для группы.

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class GroupCategoryLinkIn(BaseModel):
    # Тело запроса для link: { "category_id": 123 }
    category_id: int = Field(..., description="ID глобальной категории расходов для добавления в группу")


class GroupCategoryOut(BaseModel):
    group_id: int = Field(..., description="ID группы")
    category_id: int = Field(..., description="ID категории расходов (глобальной)")
    created_by: int | None = Field(None, description="ID пользователя, добавившего категорию")
    created_at: datetime = Field(..., description="Когда категория была добавлена в группу (UTC)")

    class Config:
        from_attributes = True
