# src/schemas/group.py
# -----------------------------------------------------------------------------
# СХЕМЫ Pydantic: Group
# -----------------------------------------------------------------------------

from __future__ import annotations

from enum import Enum
from typing import Optional, List, Literal
from datetime import date, datetime

from pydantic import BaseModel, Field

from .group_member import GroupMemberOut


class GroupStatusEnum(str, Enum):
    active = "active"
    archived = "archived"


class GroupSettleAlgoEnum(str, Enum):
    greedy = "greedy"
    pairs = "pairs"


class GroupCreate(BaseModel):
    name: str = Field(..., description="Название группы")
    description: str = Field("", description="Описание группы (необязательно)")
    owner_id: int = Field(..., description="ID владельца (может подменяться current_user на сервере)")
    # Новое: выбор алгоритма при создании (опционально; по умолчанию greedy)
    settle_algorithm: Optional[GroupSettleAlgoEnum] = Field(
        default=GroupSettleAlgoEnum.greedy,
        description="Алгоритм взаимозачёта: greedy|pairs (default: greedy)",
    )


class GroupOut(BaseModel):
    id: int = Field(..., description="ID группы")
    name: str = Field(..., description="Название группы")
    description: str = Field("", description="Описание группы")
    owner_id: Optional[int] = Field(None, description="ID владельца группы")

    status: GroupStatusEnum = Field(GroupStatusEnum.active, description="Статус: active|archived")
    archived_at: Optional[datetime] = Field(None, description="Момент архивирования (UTC)")
    deleted_at: Optional[datetime] = Field(None, description="Soft-delete метка")
    end_date: Optional[date] = Field(None, description="Дата окончания события/поездки")
    auto_archive: bool = Field(False, description="Автоархив после end_date (если нет долгов)")

    default_currency_code: str = Field("USD", description="Код валюты ISO-4217 по умолчанию")

    # Новый флаг алгоритма взаимозачёта
    settle_algorithm: GroupSettleAlgoEnum = Field(
        GroupSettleAlgoEnum.greedy,
        description="Алгоритм взаимозачёта: greedy|pairs",
    )

    # ---- Аватар группы (URL) -------------------------------------------------
    avatar_url: Optional[str] = Field(None, description="URL аватара группы")
    # -------------------------------------------------------------------------

    members: List[GroupMemberOut] = Field(default_factory=list, description="Состав группы")

    class Config:
        from_attributes = True
