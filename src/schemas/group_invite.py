# src/schemas/group_invite.py

from pydantic import BaseModel

class GroupInviteBase(BaseModel):
    group_id: int
    token: str

class GroupInviteOut(GroupInviteBase):
    id: int

    class Config:
        from_attributes = True
