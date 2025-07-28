# src/models/friend_invite.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from src.db import Base

class FriendInvite(Base):
    """
    Инвайт для приглашения новых пользователей в Splitto.
    Все инвайты бессрочные и многоразовые. Каждый invite содержит уникальный токен, id создателя и дату создания.
    """
    __tablename__ = "friend_invites"

    id = Column(Integer, primary_key=True, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())

    from_user = relationship("User", foreign_keys=[from_user_id])

    def __repr__(self):
        return f"<FriendInvite(id={self.id}, from_user_id={self.from_user_id}, token={self.token})>"
