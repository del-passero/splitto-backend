# src/models/group_category.py
# МОДЕЛЬ: Белый список категорий, разрешённых для транзакций в конкретной группе.
# ЛОГИКА:
#   - Если для группы есть записи в group_categories, то в ней можно использовать ТОЛЬКО эти категории.
#   - Если записей нет — разрешены все глобальные категории (expense_categories).
#   - Добавлять/удалять разрешённые категории может владелец группы (по нашей спецификации).
#   - Создание НОВОЙ категории (и сразу линк сюда) — только для PRO (реализуем в роутере).
#
# СХЕМА ДАННЫХ:
#   - PK (group_id, category_id) — уникальная связка.
#   - created_by — кто добавил; created_at — когда добавил.

from __future__ import annotations

from sqlalchemy import (
    Column,
    Integer,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    Index,
)
from sqlalchemy.sql import func

from ..db import Base


class GroupCategory(Base):
    __tablename__ = "group_categories"

    group_id = Column(
        Integer,
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        comment="ID группы",
    )

    # Глобальная категория расходов (таблица expense_categories)
    category_id = Column(
        Integer,
        ForeignKey("expense_categories.id", ondelete="CASCADE"),
        nullable=False,
        comment="ID глобальной категории расходов",
    )

    # Кто добавил категорию в белый список группы
    created_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Пользователь, добавивший категорию в группу",
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Когда категория была добавлена в группу",
    )

    __table_args__ = (
        PrimaryKeyConstraint("group_id", "category_id", name="pk_group_categories"),
        Index("ix_group_categories_group_id", "group_id"),
        Index("ix_group_categories_category_id", "category_id"),
    )

    # (Опционально) отношения:
    # group = relationship("Group")
    # category = relationship("ExpenseCategory")
