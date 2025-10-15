# src/models/event.py
from sqlalchemy import Column, Integer, String, DateTime, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from src.db import Base

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)

    # кто совершил действие
    actor_id = Column(Integer, nullable=False)

    # к какой группе относится (может быть NULL для персональных событий)
    group_id = Column(Integer, nullable=True)

    # над кем действие (например, дружба/удаление участника) — может быть NULL
    target_user_id = Column(Integer, nullable=True)

    # (НОВОЕ) связь с транзакцией, если событие о транзакции
    transaction_id = Column(Integer, nullable=True)

    # тип события
    type = Column(String(64), nullable=False)

    # произвольные данные события
    data = Column(JSONB, nullable=True, default={})

    created_at = Column(DateTime, nullable=False, server_default=func.now())

    # (НОВОЕ) идемпотентный ключ, чтобы не записывать дубль при ретраях
    idempotency_key = Column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_events_idempotency_key"),
    )

    def __repr__(self) -> str:
        return f"<Event id={self.id} type={self.type} actor={self.actor_id} group={self.group_id}>"
