# src/schemas/user.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    """
    Схема для создания пользователя (при регистрации через Telegram).
    Все поля опциональны кроме name и telegram_id — остальные подтягиваются из Telegram API/WebApp.
    Новые поля для is_pro и invited_friends_count можно не передавать с фронта (только через админку/бэкенд).
    """
    name: str
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    photo_url: Optional[str] = None
    language_code: Optional[str] = None
    allows_write_to_pm: Optional[bool] = True
    # --- Новые поля (для расширенного управления из админки) ---
    is_pro: Optional[bool] = False
    invited_friends_count: Optional[int] = 0

class UserOut(BaseModel):
    """
    Схема для вывода пользователя наружу (на фронт).
    """
    id: int
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    name: Optional[str] = None
    photo_url: Optional[str] = None
    language_code: Optional[str] = None
    allows_write_to_pm: Optional[bool] = None
    created_at: datetime
    updated_at: datetime
    # --- Новые поля для PRO-статуса и приглашённых друзей ---
    is_pro: bool
    invited_friends_count: int

    class Config:
        from_attributes = True
