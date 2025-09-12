# src/schemas/group.py
# -----------------------------------------------------------------------------
# СХЕМЫ Pydantic: Group
# -----------------------------------------------------------------------------
# Цели:
#   • Расширяем группу полями статуса/архивации/soft-delete и дефолтной валюты.
#   • default_currency_code — валюта ТОЛЬКО по умолчанию для новых транзакций.
#   • Состав участников оставляем в совместимом формате.
# -----------------------------------------------------------------------------

from __future__ import annotations

from enum import Enum
from typing import Optional, List
from datetime import date, datetime

from pydantic import BaseModel, Field

from .group_member import GroupMemberOut


class GroupStatusEnum(str, Enum):
    active = "active"
    archived = "archived"


class GroupCreate(BaseModel):
    name: str = Field(..., description="Название группы")
    description: str = Field("", description="Описание группы (необязательно)")
    owner_id: int = Field(..., description="ID владельца (может подменяться current_user на сервере)")


class GroupOut(BaseModel):
    # Базовое
    id: int = Field(..., description="ID группы")
    name: str = Field(..., description="Название группы")
    description: str = Field("", description="Описание группы")
    owner_id: Optional[int] = Field(None, description="ID владельца группы")

    # Состояние/ЖЦ
    status: GroupStatusEnum = Field(GroupStatusEnum.active, description="Статус: active|archived")
    archived_at: Optional[datetime] = Field(None, description="Момент архивирования (UTC)")
    deleted_at: Optional[datetime] = Field(None, description="Soft-delete метка")
    end_date: Optional[date] = Field(None, description="Дата окончания события/поездки")
    auto_archive: bool = Field(False, description="Автоархив после end_date (если нет долгов)")

    # Валюта по умолчанию для новых транзакций
    default_currency_code: str = Field("USD", description="Код валюты ISO-4217 по умолчанию")

    # Участники
    members: List[GroupMemberOut] = Field(default_factory=list, description="Состав группы")

    class Config:
        from_attributes = True
