# src/services/group_membership.py
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.group import Group
from src.models.group_member import GroupMember


def is_active_member(db: Session, group_id: int, user_id: int) -> bool:
    """
    Активный участник = запись в group_members с deleted_at IS NULL.
    """
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


# Для обратной совместимости — считаем, что "member" = "active member".
def is_member(db: Session, group_id: int, user_id: int) -> bool:
    return is_active_member(db, group_id, user_id)


def ensure_member(db: Session, group_id: int, user_id: int) -> bool:
    """
    Идемпотентно добавляет (или реактивирует) участника в группе.

    Возвращает:
      True  — если создана новая активная запись;
      False — если запись уже была активной ИЛИ мы реактивировали soft-deleted.

    Исключения:
      ValueError("group_not_found") — если группы не существует.
    """
    # 1) Группа должна существовать
    grp: Optional[Group] = db.query(Group).filter(Group.id == group_id).first()
    if not grp:
        raise ValueError("group_not_found")

    # 2) Любая запись по (group_id, user_id) — без фильтров по deleted_at
    row: Optional[GroupMember] = (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .first()
    )

    # 3) Если есть и уже активная — ничего не делаем
    if row and row.deleted_at is None:
        return False

    # 4) Если есть, но soft-deleted — реактивируем
    if row and row.deleted_at is not None:
        row.deleted_at = None
        # На случай, если в модели есть updated_at
        if hasattr(row, "updated_at"):
            setattr(row, "updated_at", datetime.utcnow())
        db.add(row)
        db.commit()
        return False

    # 5) Иначе — создаём новую запись
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
        # На случай гонки по UNIQUE (group_id, user_id) — перечитаем и считаем, что не создавали новую
        db.rollback()
        return False

    return True
