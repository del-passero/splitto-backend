# src/services/group_membership.py
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.group import Group
from src.models.group_member import GroupMember


def is_active_member(db: Session, group_id: int, user_id: int) -> bool:
    """Активный = запись есть и deleted_at IS NULL."""
    return (
        db.query(GroupMember)
        .filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
            GroupMember.deleted_at.is_(None),
        )
        .first()
        is not None
    )


# Для совместимости: считаем, что «member» = «active member»
def is_member(db: Session, group_id: int, user_id: int) -> bool:
    return is_active_member(db, group_id, user_id)


def ensure_member(db: Session, group_id: int, user_id: int) -> bool:
    """
    Идемпотентно добавляет (или реактивирует) участника.
    True  — создана новая активная запись,
    False — уже активен или была реактивация.
    """
    grp: Optional[Group] = db.query(Group).filter(Group.id == group_id).first()
    if not grp:
        raise ValueError("group_not_found")

    row: Optional[GroupMember] = (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .first()
    )

    # Уже активен
    if row and row.deleted_at is None:
        return False

    # Реактивация soft-deleted
    if row and row.deleted_at is not None:
        row.deleted_at = None
        if hasattr(row, "updated_at"):
            setattr(row, "updated_at", datetime.utcnow())
        db.add(row)
        db.commit()
        return False

    # Новая запись
    gm = GroupMember(group_id=group_id, user_id=user_id)
    now = datetime.utcnow()
    if hasattr(gm, "created_at") and getattr(gm, "created_at", None) is None:
        setattr(gm, "created_at", now)
    if hasattr(gm, "updated_at"):
        setattr(gm, "updated_at", now)

    db.add(gm)
    try:
        db.commit()
    except IntegrityError:
        # На случай гонки по UNIQUE (group_id, user_id)
        db.rollback()
        return False

    return True
