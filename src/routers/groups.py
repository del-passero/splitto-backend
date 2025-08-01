# src/routers/groups.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import secrets

from src.db import get_db
from src.models.group import Group
from src.models.group_member import GroupMember
from src.models.group_invite import GroupInvite
from src.models.user import User
from src.models.transaction import Transaction
from src.schemas.group import GroupCreate, GroupOut
from src.schemas.group_invite import GroupInviteOut
from src.schemas.group_member import GroupMemberOut 
from src.utils.balance import calculate_group_balances, greedy_settle_up
from src.schemas.settlement import SettlementOut
from src.utils.telegram_dep import get_current_telegram_user

router = APIRouter()

# =====================
# Вспомогательные функции для работы с группами
# =====================

def get_group_or_404(db: Session, group_id: int) -> Group:
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    return group

def get_group_member_ids(db: Session, group_id: int) -> List[int]:
    member_ids = [m.user_id for m in db.query(GroupMember).filter(GroupMember.group_id == group_id).all()]
    return member_ids

def get_group_transactions(db: Session, group_id: int) -> List[Transaction]:
    return db.query(Transaction)\
        .filter(Transaction.group_id == group_id, Transaction.is_deleted == False)\
        .options(joinedload(Transaction.shares)).all()

def add_member_to_group(db: Session, group_id: int, user_id: int):
    exists = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == user_id
    ).first()
    if not exists:
        db_member = GroupMember(group_id=group_id, user_id=user_id)
        db.add(db_member)
        db.commit()
        db.refresh(db_member)

# =====================
# Основные роуты для управления группами и участниками
# =====================

@router.get("/{group_id}/balances")
def get_group_balances(group_id: int, db: Session = Depends(get_db)):
    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)
    net_balance = calculate_group_balances(transactions, member_ids)
    return [
        {"user_id": uid, "balance": round(balance, 2)}
        for uid, balance in net_balance.items()
    ]

@router.get("/{group_id}/settle-up", response_model=List[SettlementOut])
def get_group_settle_up(group_id: int, db: Session = Depends(get_db)):
    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)
    net_balance = calculate_group_balances(transactions, member_ids)
    settlements = greedy_settle_up(net_balance)
    return settlements

@router.post("/", response_model=GroupOut)
def create_group(group: GroupCreate, db: Session = Depends(get_db)):
    db_group = Group(name=group.name, description=group.description, owner_id=group.owner_id)
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    add_member_to_group(db, db_group.id, db_group.owner_id)
    return db_group

@router.get("/", response_model=List[GroupOut])
def get_groups(db: Session = Depends(get_db)):
    return db.query(Group).all()

@router.get("/user/{user_id}")
def get_groups_for_user(
    user_id: int, 
    db: Session = Depends(get_db),
    members_preview_limit: int = Query(4, gt=0)
):
    group_ids = db.query(GroupMember.group_id).filter(GroupMember.user_id == user_id).subquery()
    groups = db.query(Group).filter(Group.id.in_(group_ids)).all()
    result = []
    for group in groups:
        members = db.query(GroupMember).filter(GroupMember.group_id == group.id).limit(members_preview_limit).all()
        member_objs = [GroupMemberOut.from_orm(m) for m in members]
        member_ids = set([m.user_id for m in members])
        member_ids.add(group.owner_id)
        owner_member = next((m for m in member_objs if m.user.id == group.owner_id), None)
        if owner_member:
            member_objs.remove(owner_member)
            member_objs = [owner_member] + member_objs
        result.append({
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "owner_id": group.owner_id,
            "members_count": len(member_ids),
            "preview_members": member_objs  # <--- превью с лимитом!
        })
    return result

@router.get("/{group_id}/detail/", response_model=GroupOut)
def group_detail(
    group_id: int,
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, gt=0)
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    if limit is not None:
        group.members = db.query(GroupMember).filter(GroupMember.group_id == group_id).offset(offset).limit(limit).all()
    else:
        group.members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    return group

# =====================
# Роуты для управления инвайтами (приглашениями) в группу
# =====================

@router.post("/{group_id}/invite", response_model=GroupInviteOut)
def create_group_invite(group_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_telegram_user)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    invite = db.query(GroupInvite).filter(GroupInvite.group_id == group_id).first()
    if not invite:
        token = secrets.token_urlsafe(16)
        invite = GroupInvite(group_id=group_id, token=token)
        db.add(invite)
        db.commit()
        db.refresh(invite)
    return invite

@router.post("/accept-invite")
def accept_group_invite(token: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_telegram_user)):
    invite = db.query(GroupInvite).filter(GroupInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Инвайт не найден")
    group_id = invite.group_id
    add_member_to_group(db, group_id, current_user.id)
    return {"detail": "Успешно добавлен в группу"}
