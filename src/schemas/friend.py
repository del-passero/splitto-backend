# src/schemas/friend.py

from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from src.schemas.user import UserOut  # Абсолютный импорт схемы пользователя

class FriendCreate(BaseModel):
    """
    Схема для создания дружбы (отправка заявки в друзья).
    """
    user_id: int
    friend_id: int

class FriendOut(BaseModel):
    """
    Схема для выдачи полной информации о связи дружбы.
    Содержит:
        - статус (pending/accepted/blocked)
        - даты создания/обновления
        - вложенные объекты user и friend (UserOut) для удобства фронта
    """
    id: int
    user_id: int
    friend_id: int
    status: str
    created_at: datetime
    updated_at: datetime
    user: UserOut
    friend: UserOut

    class Config:
        from_attributes = True
