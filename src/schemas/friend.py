# src/schemas/friend.py
from pydantic import BaseModel
from datetime import datetime
from src.schemas.user import UserOut  # Абсолютный импорт схемы пользователя


class FriendCreate(BaseModel):
    """
    Схема создания дружбы (через инвайт или прямое добавление).
    Для совместимости оставляем поля старого формата.
    """
    user_id: int
    friend_id: int


class FriendOut(BaseModel):
    """
    Выдача одной связи дружбы в формате, удобном фронту:
      - user     -> профиль ДРУГА (UserOut)
      - friend   -> профиль ВЛАДЕЛЬЦА списка (или текущего пользователя)
      - hidden   -> скрыт ли ДРУГ для владельца списка/текущего пользователя
      - id, user_id, friend_id, created_at, updated_at — для ссылок/отладок
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
