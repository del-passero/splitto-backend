# src/schemas/user.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    """
    Схема для создания пользователя (при регистрации через Telegram).
    Все поля опциональны кроме name и telegram_id — остальные подтягиваются из Telegram API/WebApp.
    """
    name: str
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    photo_url: Optional[str] = None
    language_code: Optional[str] = None
    allows_write_to_pm: Optional[bool] = True

class UserOut(BaseModel):
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

    class Config:
        from_attributes = True
