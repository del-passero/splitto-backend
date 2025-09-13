# src/schemas/user.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    name: str
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    photo_url: Optional[str] = None
    language_code: Optional[str] = None
    allows_write_to_pm: Optional[bool] = True
    is_pro: Optional[bool] = False
    invited_friends_count: Optional[int] = 0

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
    is_pro: bool
    invited_friends_count: int

    class Config:
        from_attributes = True
