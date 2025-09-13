# src/schemas/group_member.py
from pydantic import BaseModel
from .user import UserOut

class GroupMemberCreate(BaseModel):
    group_id: int
    user_id: int

class GroupMemberOut(BaseModel):
    id: int
    group_id: int
    user: UserOut
    class Config:
        from_attributes = True
