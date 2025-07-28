# src/models/invite_usage.py

from sqlalchemy import Column, Integer, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from src.db import Base

class InviteUsage(Base):
    """
    Факт первого входа пользователя в Splitto по конкретному invite.

    Особенности:
        - Хранится только для новых пользователей (только первый invite).
        - Поле used_at для истории и аналитики.
    """
    __tablename__ = "invite_usages"

    id = Column(Integer, primary_key=True)
    invite_id = Column(Integer, ForeignKey("friend_invites.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    used_at = Column(DateTime, nullable=False, default=func.now())

    invite = relationship("FriendInvite", foreign_keys=[invite_id])
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return f"<InviteUsage(invite_id={self.invite_id}, user_id={self.user_id}, used_at={self.used_at})>"
