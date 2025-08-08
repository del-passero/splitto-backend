# src/models/group_hidden.py
# МОДЕЛЬ: Персональное скрытие группы для конкретного пользователя.
# ЛОГИКА:
#   - Это НЕ архив (архив — глобально для всех). Это только пользовательское скрытие.
#   - Запись существует, если пользователь спрятал эту группу из своих списков.
#   - Данные группы продолжают участвовать в отчётах/балансе/поиске (если фронт попросит).
#   - PK составной (group_id, user_id) — одна запись на пользователя на группу.
#
# ИСПОЛЬЗОВАНИЕ:
#   - При выборке "мои группы" по умолчанию делаем LEFT JOIN и отфильтровываем там,
#     где group_hidden IS NULL (если include_hidden=false).
#   - Для отображения скрытых — параметр include_hidden=true.
#
# Примечание: CASCADE даём осознанно (при удалении пользователя/группы запись скрытия должна исчезнуть).

from __future__ import annotations

from sqlalchemy import Column, Integer, DateTime, ForeignKey, PrimaryKeyConstraint, Index, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..db import Base


class GroupHidden(Base):
    __tablename__ = "group_hidden"

    # FK на группу (при удалении группы — скрытия для неё удаляются)
    group_id = Column(
        Integer,
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        comment="ID группы",
    )

    # FK на пользователя (при удалении пользователя — его личные настройки скрытия удаляются)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="ID пользователя, для которого группа скрыта",
    )

    # Когда пользователь спрятал группу (UTC)
    hidden_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Момент, когда пользователь скрыл группу",
    )

    # Составной первичный ключ — не допускаем дубликатов скрытия для одной пары
    __table_args__ = (
        PrimaryKeyConstraint("group_id", "user_id", name="pk_group_hidden"),
        # Индекс на user_id для быстрых выборок «все мои скрытые группы»
        Index("ix_group_hidden_user_id", "user_id"),
    )

    # (Опционально) связи:
    # group = relationship("Group")
    # user = relationship("User")
