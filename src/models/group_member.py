from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship
from ..db import Base

class GroupMember(Base):
    __tablename__ = "group_members"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    group = relationship("Group")
    user = relationship("User")
