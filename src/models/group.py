# src/models/group.py
# -----------------------------------------------------------------------------
# МОДЕЛЬ: Group (SQLAlchemy)
# -----------------------------------------------------------------------------

from __future__ import annotations

import enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    Enum,
    Date,
    DateTime,
    Boolean,
    Index,
    text,
)
from sqlalchemy.orm import relationship

from ..db import Base


class GroupStatus(enum.Enum):
    active = "active"
    archived = "archived"


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, default="")

    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User")

    status = Column(
        Enum(GroupStatus, name="group_status"),
        nullable=False,
        default=GroupStatus.active,
        server_default=text("'active'"),
        comment="Статус группы: active|archived",
    )

    archived_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Когда перевели в archived (UTC)",
    )

    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Soft-delete метка; если не NULL — группа скрыта",
    )

    end_date = Column(
        Date,
        nullable=True,
        comment="Дата окончания события/поездки (для автоархивации)",
    )

    auto_archive = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Автоматически архивировать после end_date (если нет долгов)",
    )

    default_currency_code = Column(
        String(3),
        nullable=False,
        default="USD",
        server_default=text("'USD'"),
        comment="Дефолтная валюта группы (ISO-4217, напр., 'USD')",
    )

    __table_args__ = (
        Index("ix_groups_status", "status"),
        Index("ix_groups_deleted_at", "deleted_at"),
        Index("ix_groups_end_date_auto_archive", "end_date", "auto_archive"),
        Index("ix_groups_default_currency_code", "default_currency_code"),
    )
