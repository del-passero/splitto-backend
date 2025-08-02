# src/routers/group_members.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from src.models.group_member import GroupMember
from src.models.friend import Friend
from src.schemas.group_member import GroupMemberCreate, GroupMemberOut
from src.db import get_db
from src.models.user import User

from typing import List, Optional, Union

router = APIRouter()

def add_mutual_friends_for_group(db: Session, group_id: int):
    """
    Для всех участников группы создаёт двусторонние связи Friend (если ещё нет).
    Использовать после добавления нового участника в группу.
    """
    member_ids = [m.user_id for m in db.query(GroupMember).filter(GroupMember.group_id == group_id).all()]
    for i in range(len(member_ids)):
        for j in range(i + 1, len(member_ids)):
            a, b = member_ids[i], member_ids[j]
            # Добавляем связь a <-> b двусторонне
            for x, y in [(a, b), (b, a)]:
                exists = db.query(Friend).filter(
                    Friend.user_id == x, Friend.friend_id == y
                ).first()
                if not exists:
                    db.add(Friend(user_id=x, friend_id=y))
    db.commit()

@router.post("/", response_model=GroupMemberOut)
def add_group_member(member: GroupMemberCreate, db: Session = Depends(get_db)):
    """
    Добавить нового участника в группу.
    После добавления автоматически добавить всем участникам группы друг друга в друзья (двусторонне).
    """
    # Проверка на существование такой записи
    exists = db.query(GroupMember).filter(
        GroupMember.group_id == member.group_id,
        GroupMember.user_id == member.user_id
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Пользователь уже в группе")
    db_member = GroupMember(group_id=member.group_id, user_id=member.user_id)
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    # --- КЛЮЧЕВОЕ: автодобавление всех участников друг другу в друзья! ---
    add_mutual_friends_for_group(db, member.group_id)
    return db_member

@router.get("/", response_model=Union[List[GroupMemberOut], dict])
def get_group_members(
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, gt=0)
):
    """
    Получить список всех участников (или пагинированно, если передан limit).
    Если передан limit — вернётся {"total": ..., "items": [...]}
    """
    query = db.query(GroupMember)
    total = query.count()
    if limit is not None:
        members = query.offset(offset).limit(limit).all()
    else:
        members = query.all()
    items = [GroupMemberOut.from_orm(m) for m in members]
    if limit is not None:
        return {"total": total, "items": items}
    else:
        return items

@router.get("/group/{group_id}", response_model=Union[List[dict], dict])
def get_members_for_group(
    group_id: int,
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, gt=0)
):
    """
    Получить участников конкретной группы (или пагинированно).
    Если передан limit — вернётся {"total": ..., "items": [...]}
    """
    query = db.query(GroupMember, User)\
        .join(User, GroupMember.user_id == User.id)\
        .filter(GroupMember.group_id == group_id)
    total = query.count()
    if limit is not None:
        memberships = query.offset(offset).limit(limit).all()
    else:
        memberships = query.all()
    items = [
        {
            "id": gm.id,
            "group_id": gm.group_id,
            "user": {
                "id": u.id,
                "name": u.name,
                "telegram_id": u.telegram_id,
            }
        }
        for gm, u in memberships
    ]
    if limit is not None:
        return {"total": total, "items": items}
    else:
        return items

@router.delete("/{member_id}", status_code=204)
def delete_group_member(member_id: int, db: Session = Depends(get_db)):
    member = db.query(GroupMember).filter(GroupMember.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Участник группы не найден")
    db.delete(member)
    db.commit()
    return
