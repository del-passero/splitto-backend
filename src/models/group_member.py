# src/models/group_member.py
# Модель участника группы + уникальность (group_id, user_id) + soft-delete (deleted_at)

from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db import Base


class GroupMember(Base):
    __tablename__ = "group_members"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # soft-delete для членства
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),
        Index("ix_group_members_group_active", "group_id", "deleted_at"),
        Index("ix_group_members_user_active", "user_id", "deleted_at"),
    )

    group = relationship("Group")
    user = relationship("User")
