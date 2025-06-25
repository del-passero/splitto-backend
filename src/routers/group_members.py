from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.models.group_member import GroupMember
from src.models.user import User
from src.schemas.group_member import GroupMemberCreate, GroupMemberOut
from src.db import get_db
from typing import List

router = APIRouter()

@router.post("/", response_model=GroupMemberOut)
def add_group_member(member: GroupMemberCreate, db: Session = Depends(get_db)):
    db_member = GroupMember(group_id=member.group_id, user_id=member.user_id)
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    return db_member

@router.get("/", response_model=List[GroupMemberOut])
def get_group_members(db: Session = Depends(get_db)):
    return db.query(GroupMember).all()

@router.get("/group/{group_id}")
def get_members_for_group(group_id: int, db: Session = Depends(get_db)):
    memberships = (
        db.query(GroupMember, User)
        .join(User, GroupMember.user_id == User.id)
        .filter(GroupMember.group_id == group_id)
        .all()
    )
    return [
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

@router.delete("/{member_id}", status_code=204)
def delete_group_member(member_id: int, db: Session = Depends(get_db)):
    member = db.query(GroupMember).filter(GroupMember.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Участник группы не найден")
    db.delete(member)
    db.commit()
    return
