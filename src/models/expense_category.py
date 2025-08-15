# src/models/expense_category.py
# МОДЕЛЬ СПРАВОЧНИКА КАТЕГОРИЙ (как у валют): key, name_i18n (ru/en/es), parent_id (self-FK),
# icon, color, is_active, timestamps. Уникальность по key, индекс по parent_id.

from __future__ import annotations

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from ..db import Base


class ExpenseCategory(Base):
    """
    Справочник категорий расходов:
      - Топ-категории: parent_id = NULL, у них задаём color
      - Подкатегории: parent_id = id топ-категории, у них обязательна icon (emoji)
      - Локализованные названия: name_i18n = {"ru": "...", "en": "...", "es": "..."}
    """
    __tablename__ = "expense_categories"

    id = Column(Integer, primary_key=True, index=True)

    # Стабильный ключ категории (ASCII, snake_case), как у валют code/name_i18n
    key = Column(String(64), nullable=False, unique=True, comment="Стабильный ключ категории (snake_case)")

    # Иерархия: ссылка на родителя (NULL для топ-категорий)
    parent_id = Column(Integer, ForeignKey("expense_categories.id", ondelete="CASCADE"), nullable=True)

    # Emoji или код иконки; для подкатегорий обязательно; для топов — опционально
    icon = Column(String, nullable=True, comment="Эмодзи/иконка категории")

    # Цвет (HEX), задаём обычно на топ-категориях
    color = Column(String(7), nullable=True, comment="Цвет категорий (HEX), обычно у топ-категории")

    # Локализованные названия: как у валют name_i18n
    name_i18n = Column(JSONB, nullable=False, comment="Локализованные названия: {'ru':..., 'en':..., 'es':...}")

    # Флаги и таймстемпы
    is_active = Column(Boolean, nullable=False, server_default="true", comment="Активная категория")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # key — уникален во всём справочнике
        UniqueConstraint("key", name="uq_expense_categories_key"),
        # Быстрый выбор подкатегорий по топу
        Index("ix_expense_categories_parent_id", "parent_id"),
        Index("ix_expense_categories_is_active", "is_active"),
    )

    # Связи self-referential
    parent = relationship("ExpenseCategory", remote_side=[id], backref="children", lazy="joined")
