# src/models/friend.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, UniqueConstraint, func
from sqlalchemy.orm import relationship
from src.db import Base

class Friend(Base):
    """
    Модель связи дружбы между двумя пользователями.

    Основные особенности:
        - Дружба двусторонняя: на каждый accepted есть две записи (user_id → friend_id и friend_id → user_id).
        - Есть поле status: 'pending' (ожидание), 'accepted' (дружба), 'blocked' (блокировка).
        - created_at, updated_at для аудита и правильной работы запросов.
        - Связи на оба объекта User (user, friend).
    """
    __tablename__ = "friends"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    friend_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    status = Column(String, default="pending", nullable=False)  # pending / accepted / blocked
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Уникальная пара: один user не может добавить одного и того же друга дважды
    __table_args__ = (UniqueConstraint('user_id', 'friend_id', name='_user_friend_uc'),)

    # Связи для быстрого доступа к объектам User
    user = relationship("User", foreign_keys=[user_id], backref="my_friends")
    friend = relationship("User", foreign_keys=[friend_id], backref="friend_of")

    def __repr__(self):
        return f"<Friend(user_id={self.user_id}, friend_id={self.friend_id}, status={self.status})>"
