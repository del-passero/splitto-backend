# src/models/group_invite.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from src.db import Base

class GroupInvite(Base):
    """
    Модель для хранения инвайтов-приглашений в группу.
    Каждый инвайт содержит уникальный токен и связан с конкретной группой.
    """
    __tablename__ = "group_invites"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())

    group = relationship("Group", foreign_keys=[group_id])

    def __repr__(self):
        return f"<GroupInvite(id={self.id}, group_id={self.group_id}, token={self.token})>"
