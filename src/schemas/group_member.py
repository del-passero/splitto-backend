from pydantic import BaseModel
from .user import UserOut  # Импортируй схему пользователя (см. user.py)

class GroupMemberCreate(BaseModel):
    group_id: int
    user_id: int

class GroupMemberOut(BaseModel):
    id: int
    group_id: int
    user: UserOut              # <<< Вот это ключевое изменение!
    class Config:
        from_attributes = True
