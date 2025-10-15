# src/schemas/event.py
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel

class EventOut(BaseModel):
    id: int
    type: str
    actor_id: int
    group_id: Optional[int] = None
    target_user_id: Optional[int] = None
    transaction_id: Optional[int] = None  # новое
    data: Optional[Dict[str, Any]] = None
    created_at: datetime
    idempotency_key: Optional[str] = None  # новое

    class Config:
        from_attributes = True
