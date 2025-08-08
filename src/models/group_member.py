# src/models/group_member.py
# Модель участника группы + уникальность (group_id, user_id)

from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from ..db import Base


class GroupMember(Base):
    __tablename__ = "group_members"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Уникальная связка: один пользователь может быть в группе только один раз
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),
    )

    # Отношения (оставляем как у тебя было)
    group = relationship("Group")
    user = relationship("User")
