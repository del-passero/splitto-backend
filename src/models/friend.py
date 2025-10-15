# src/models/friend.py
from sqlalchemy import (
    Column, Integer, ForeignKey, DateTime,
    UniqueConstraint, Boolean, func, Index, CheckConstraint
)
from sqlalchemy.orm import relationship
from src.db import Base


class Friend(Base):
    """
    Каноническая модель дружбы: одна строка на пару пользователей.
    Пара хранится как (user_min, user_max) с инвариантом user_min < user_max.
    Персональные флаги скрытия: hidden_by_min / hidden_by_max.
    """
    __tablename__ = "friends"

    id = Column(Integer, primary_key=True, index=True)

    user_min = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_max = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    hidden_by_min = Column(Boolean, nullable=False, default=False)
    hidden_by_max = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_min", "user_max", name="uq_friend_pair"),
        CheckConstraint("user_min < user_max", name="ck_friend_min_lt_max"),
        Index("ix_friends_user_min", "user_min"),
        Index("ix_friends_user_max", "user_max"),
    )

    user_min_rel = relationship("User", foreign_keys=[user_min], backref="friendships_as_min")
    user_max_rel = relationship("User", foreign_keys=[user_max], backref="friendships_as_max")

    def __repr__(self):
        return f"<Friend(user_min={self.user_min}, user_max={self.user_max})>"
