# src/services/group_membership.py
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
from typing import Optional

from src.models.group import Group
from src.models.group_member import GroupMember

def is_member(db: Session, group_id: int, user_id: int) -> bool:
    return db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == user_id
    ).first() is not None

def ensure_member(db: Session, group_id: int, user_id: int) -> bool:
    """
    Идемпотентно добавляет участника в группу.
    Возвращает True, если был создан новый участник.
    """
    if is_member(db, group_id, user_id):
        return False
    # Проверим, что группа существует
    grp: Optional[Group] = db.query(Group).filter(Group.id == group_id).first()
    if not grp:
        raise ValueError("group_not_found")

    gm = GroupMember(group_id=group_id, user_id=user_id)
    # На случай non-null дат — проставим, если такие поля есть в модели
    if hasattr(gm, "created_at") and getattr(gm, "created_at") is None:
        setattr(gm, "created_at", datetime.utcnow())
    if hasattr(gm, "updated_at"):
        setattr(gm, "updated_at", datetime.utcnow())

    db.add(gm)
    db.commit()
    return True
