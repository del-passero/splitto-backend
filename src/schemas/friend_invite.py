# src/schemas/friend_invite.py

from pydantic import BaseModel

class FriendInviteBase(BaseModel):
    from_user_id: int
    token: str

class FriendInviteOut(FriendInviteBase):
    id: int

    class Config:
        from_attributes = True
