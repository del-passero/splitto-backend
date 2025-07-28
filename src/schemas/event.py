# src/schemas/event.py

from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime

class EventBase(BaseModel):
    actor_id: int
    target_user_id: Optional[int]
    group_id: Optional[int]
    type: str
    data: Optional[Any]
    created_at: Optional[datetime] = None

class EventOut(EventBase):
    id: int

    class Config:
        orm_mode = True
