# src/models/event.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, JSON
from sqlalchemy.orm import relationship
from src.db import Base

class Event(Base):
    """
    ”ниверсальное событие дл¤ ленты активности (event feed).

    ќсобенности:
        - actor_id Ч инициатор (всегда кто-то из User).
        - target_user_id, group_id Ч опционально (если событие св¤зано с другим пользователем или группой).
        - type Ч строка-ключ событи¤ (например, 'friend_added', 'invite_registered', 'transaction_created').
        - data Ч любые дополнительные параметры (сумма, имена, id, текст).
        - created_at Ч врем¤ событи¤.
    """
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    type = Column(String, nullable=False)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())

    actor = relationship("User", foreign_keys=[actor_id])
    target_user = relationship("User", foreign_keys=[target_user_id])
    # group Ч св¤зь с группой, если модель группы у теб¤ есть

    def __repr__(self):
        return f"<Event(type={self.type}, actor_id={self.actor_id}, target_user_id={self.target_user_id}, group_id={self.group_id})>"
