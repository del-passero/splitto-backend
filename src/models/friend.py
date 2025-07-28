# src/models/friend.py

from sqlalchemy import Column, Integer, ForeignKey, DateTime, UniqueConstraint, Boolean, func
from sqlalchemy.orm import relationship
from src.db import Base

class Friend(Base):
    """
    Модель связи дружбы между двумя пользователями.

    Особенности:
        - Дружба всегда двусторонняя: на каждую дружбу есть две записи (user_id → friend_id и friend_id → user_id).
        - created_at, updated_at для аудита.
        - Связи на оба объекта User (user, friend).
        - Можно скрыть друга, если поле hidden=True.
    """
    __tablename__ = "friends"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    friend_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    hidden = Column(Boolean, default=False)  # Скрыт ли друг в списке (True — скрыт, False — виден)
    # Можно добавить status (например, pending, blocked и т.д.), если понадобится расширенная логика

    __table_args__ = (UniqueConstraint('user_id', 'friend_id', name='_user_friend_uc'),)

    user = relationship("User", foreign_keys=[user_id], backref="my_friends")
    friend = relationship("User", foreign_keys=[friend_id], backref="friend_of")

    def __repr__(self):
        return f"<Friend(user_id={self.user_id}, friend_id={self.friend_id})>"
