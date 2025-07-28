# src/schemas/friend.py

from pydantic import BaseModel
from datetime import datetime
from src.schemas.user import UserOut  # Абсолютный импорт схемы пользователя

class FriendCreate(BaseModel):
    """
    Схема для создания дружбы.
    """
    user_id: int
    friend_id: int

class FriendOut(BaseModel):
    """
    Схема для выдачи полной информации о связи дружбы.
    Содержит:
        - даты создания/обновления
        - вложенные объекты user и friend (UserOut) для удобства фронта
        - статус hidden
    """
    id: int
    user_id: int
    friend_id: int
    created_at: datetime
    updated_at: datetime
    user: UserOut
    friend: UserOut
    hidden: bool

    class Config:
        from_attributes = True
