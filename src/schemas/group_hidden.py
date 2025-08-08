# src/schemas/group_hidden.py
# СХЕМЫ: персональное скрытие группы (выдача и, при необходимости, создание).

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class GroupHiddenOut(BaseModel):
    group_id: int = Field(..., description="ID группы")
    user_id: int = Field(..., description="ID пользователя")
    hidden_at: datetime = Field(..., description="Когда группа была скрыта пользователем (UTC)")

    class Config:
        from_attributes = True
