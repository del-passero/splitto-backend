# src/schemas/invite_usage.py

from pydantic import BaseModel
from datetime import datetime

class InviteUsageBase(BaseModel):
    invite_id: int
    user_id: int
    used_at: datetime

class InviteUsageOut(InviteUsageBase):
    id: int

    class Config:
        from_attributes = True
