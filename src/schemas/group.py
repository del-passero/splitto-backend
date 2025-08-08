# src/schemas/group.py
# Pydantic-схемы для работы с группами.
# Цель: расширить существующий GroupOut новыми полями (статус, архив/удаление, дата окончания,
# автоархив, валюта по умолчанию), не ломая текущие контракты.
# ВАЖНО: старый функционал НЕ удаляем. GroupCreate оставляем совместимой.

from __future__ import annotations

from enum import Enum
from typing import Optional, List
from datetime import date, datetime

from pydantic import BaseModel, Field

from .group_member import GroupMemberOut  # схема участника группы


class GroupStatusEnum(str, Enum):
    """
    Перечисление статусов группы на уровне схем (Pydantic).
    Используем строковые значения для удобной сериализации в JSON.
    """
    active = "active"     # обычное состояние (группа активна, разрешены изменения)
    archived = "archived" # «скрыта для всех» и read-only (изменения запрещены, но просмотр разрешён)


class GroupCreate(BaseModel):
    """
    Схема для создания новой группы.
    Мы сохраняем совместимость с текущими ручками:
      - name — обязательное поле.
      - description — необязательное (по умолчанию пустая строка).
      - owner_id — обязателен (на бэке всё равно подменяется текущим пользователем).
    """
    name: str = Field(..., description="Название группы")
    description: str = Field("", description="Описание группы (необязательно)")
    owner_id: int = Field(..., description="ID владельца группы (может подменяться на current_user на сервере)")


class GroupOut(BaseModel):
    """
    Полная выдача группы.
    ДОБАВЛЕНЫ поля статуса/архива/удаления/автоархива/даты окончания/валюты.
    Порядок полей подобран так, чтобы не мешать текущему фронту.
    """
    # Базовая информация
    id: int = Field(..., description="ID группы")
    name: str = Field(..., description="Название группы")
    description: str = Field("", description="Описание группы")
    owner_id: Optional[int] = Field(None, description="ID владельца группы")

    # Новый блок: состояние и управление жизненным циклом
    status: GroupStatusEnum = Field(GroupStatusEnum.active, description="Статус группы: active|archived")
    archived_at: Optional[datetime] = Field(None, description="Когда группа была заархивирована (UTC)")
    deleted_at: Optional[datetime] = Field(None, description="Soft-delete метка (если не NULL — группа 'удалена')")
    end_date: Optional[date] = Field(None, description="Дата окончания события/поездки (для автоархивации)")
    auto_archive: bool = Field(False, description="Автоматически архивировать после end_date (если нет долгов)")

    # Валюта по умолчанию
    default_currency_code: str = Field("USD", description="Код валюты ISO-4217 по умолчанию для группы")

    # Участники (оставляем как было — важная часть контракта)
    members: List[GroupMemberOut] = Field(
        default_factory=list,
        description="Список участников группы (может приходить пустым при некоторых выборках)"
    )

    class Config:
        # В FastAPI + SQLAlchemy это позволяет создавать схему из ORM-объекта без ручного маппинга.
        from_attributes = True
