from pydantic import BaseModel

class GroupMemberCreate(BaseModel):
    group_id: int
    user_id: int

class GroupMemberOut(BaseModel):
    id: int
    group_id: int
    user_id: int
    class Config:
        orm_mode = True
