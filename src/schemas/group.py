from pydantic import BaseModel
from typing import Optional

class GroupCreate(BaseModel):
    name: str
    description: str = ""
    owner_id: int

class GroupOut(BaseModel):
    id: int
    name: str
    description: str
    owner_id: Optional[int]
    class Config:
        orm_mode = True
