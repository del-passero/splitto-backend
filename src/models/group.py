# src/models/group.py
# МОДЕЛЬ ГРУППЫ (SQLAlchemy 2.x) С ПОЛНЫМ КОММЕНТИРОВАНИЕМ.
# ВАЖНО: Мы НЕ удаляем старые поля и поведение — только ДОБАВЛЯЕМ новые.
# Эта модель соответствует согласованной спецификации:
#   - статус группы (active|archived),
#   - архивирование для всех,
#   - soft-delete,
#   - дата окончания + авто-архив,
#   - валюта группы по умолчанию.
#
# МИГРАЦИИ: для новых колонок и индексов потребуется Alembic-миграция (сделаем позже отдельным шагом).

from __future__ import annotations

from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    Enum,        # тип для статуса группы
    Date,        # дата окончания события/поездки
    DateTime,    # время архивирования/удаления
    Boolean,     # флаг автоархивации
    Index,       # индексы для быстрых выборок
    text,        # server_default при необходимости строкой
)
from sqlalchemy.orm import relationship
import enum

from ..db import Base


class GroupStatus(enum.Enum):
    """
    Перечисление возможных статусов группы.
    - active   — обычное состояние (можно создавать транзакции/инвайты/менять участников).
    - archived — «скрыто для всех»/read-only (без возможности мутаций), НО группа остаётся в БД.
    """
    active = "active"
    archived = "archived"


class Group(Base):
    """
    Модель группы.

    СТАРЫЕ ПОЛЯ (не трогаем):
      - id, name, description, owner_id, owner — как были в твоём коде.

    НОВЫЕ ПОЛЯ:
      - status                 — текущий статус группы (active|archived).
      - archived_at            — когда группа была заархивирована (None, если активна).
      - deleted_at             — soft-delete метка (None, если не удалена).
      - end_date               — дата окончания события/поездки; используется авто-архивом.
      - auto_archive           — включить ли авто-архив по end_date.
      - default_currency_code  — 3-буквенный код валюты ISO-4217 (валюта группы по умолчанию).

    ТАБЛИЧНЫЕ ИНДЕКСЫ:
      - по status, deleted_at, (end_date, auto_archive), default_currency_code — для выборок и джоб.
    """

    __tablename__ = "groups"

    # === СТАРЫЕ ПОЛЯ (оставляем без изменений) ===
    id = Column(Integer, primary_key=True, index=True)  # PK
    name = Column(String, index=True)                   # название (как было)
    description = Column(String, default="")            # описание (как было)

    owner_id = Column(Integer, ForeignKey("users.id"))  # владелец
    owner = relationship("User")                        # связь с пользователем-владельцем

    # === НОВЫЕ ПОЛЯ ===

    # Статус группы: active / archived.
    # default и server_default задаём сразу, чтобы при миграции существующие записи получили 'active'
    status = Column(
        Enum(GroupStatus, name="group_status"),
        nullable=False,
        default=GroupStatus.active,                # дефолт на уровне Python
        server_default=text("'active'"),           # дефолт на уровне БД (важно для alembic/существующих строк)
        index=False,                               # сам Enum мы не индексируем как колонку — см. __table_args__ ниже
        comment="Текущий статус группы: active|archived",
    )

    # Когда заархивировали (None — не архивирована).
    archived_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Момент перевода группы в статус 'archived'",
    )

    # Soft-delete метка. Если не NULL — группу скрываем вообще из всех выборок по умолчанию.
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Soft-delete: если не NULL — группа 'удалена' (восстановима)",
    )

    # Плановая дата окончания поездки/события. Используется задачей авто-архива.
    end_date = Column(
        Date,
        nullable=True,
        comment="Дата окончания события/поездки. Для автоархивации.",
    )

    # Включён ли авто-архив по end_date. Если true и end_date прошла, и долгов нет — архивируем.
    auto_archive = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Автоматически архивировать группу после end_date (если нет долгов).",
    )

    # Валюта группы по умолчанию (3-буквенный код ISO-4217). Пока все транзакции группы должны быть в этой валюте.
    default_currency_code = Column(
        String(3),
        nullable=False,
        default="USD",
        server_default=text("'USD'"),
        comment="Валюта группы по умолчанию (ISO-4217, напр. 'USD').",
    )

    # Примечание: связь с участниками (GroupMember) не добавляем здесь через back_populates,
    # чтобы не ломать текущие модели. Если в твоём GroupMember уже есть relationship('Group'),
    # двухсторонная связь не обязательна и может быть добавлена позже синхронно с правкой group_member.py.

    # Индексы выносим в __table_args__ — так читаемее и под контролем миграций.
    __table_args__ = (
        Index("ix_groups_status", "status"),
        Index("ix_groups_deleted_at", "deleted_at"),
        Index("ix_groups_end_date_auto_archive", "end_date", "auto_archive"),
        Index("ix_groups_default_currency_code", "default_currency_code"),
    )
