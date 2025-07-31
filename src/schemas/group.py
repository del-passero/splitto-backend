from pydantic import BaseModel
from typing import Optional, List
from .group_member import GroupMemberOut    # Импорт схемы участника!

class GroupCreate(BaseModel):
    name: str
    description: str = ""
    owner_id: int

class GroupOut(BaseModel):
    id: int
    name: str
    description: str
    owner_id: Optional[int]
    members: List[GroupMemberOut] = []      # <<< Ключевая строка!
    class Config:
        from_attributes = True

