# src/routers/groups.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List
from src.db import get_db
from src.models.group import Group
from src.models.group_member import GroupMember
from src.models.user import User
from src.models.transaction import Transaction
from src.schemas.group import GroupCreate, GroupOut
from src.utils.balance import calculate_group_balances, greedy_settle_up
from src.schemas.settlement import SettlementOut

router = APIRouter()

# =====================
# Вспомогательные функции
# =====================

def get_group_or_404(db: Session, group_id: int) -> Group:
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    return group

def get_group_member_ids(db: Session, group_id: int) -> List[int]:
    member_ids = [m.user_id for m in db.query(GroupMember).filter(GroupMember.group_id == group_id).all()]
    group = get_group_or_404(db, group_id)
    if group.owner_id and group.owner_id not in member_ids:
        member_ids.append(group.owner_id)
    return member_ids

def get_group_transactions(db: Session, group_id: int) -> List[Transaction]:
    return db.query(Transaction)\
        .filter(Transaction.group_id == group_id, Transaction.is_deleted == False)\
        .options(joinedload(Transaction.shares)).all()

# =====================
# Основные роуты
# =====================

@router.get("/{group_id}/balances")
def get_group_balances(
    group_id: int,
    db: Session = Depends(get_db)
):
    """
    Возвращает net balance для каждого участника группы (кому должны и кто должен).
    """
    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)
    net_balance = calculate_group_balances(transactions, member_ids)
    # Список словарей с user_id и балансом
    return [
        {"user_id": uid, "balance": round(balance, 2)}
        for uid, balance in net_balance.items()
    ]

@router.get("/{group_id}/settle-up", response_model=List[SettlementOut])
def get_group_settle_up(
    group_id: int,
    db: Session = Depends(get_db)
):
    """
    Возвращает оптимальный (жадный) список переводов (settle-up) между участниками группы.
    """
    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)
    net_balance = calculate_group_balances(transactions, member_ids)
    settlements = greedy_settle_up(net_balance)
    return settlements

# СТАРЫЕ РОУТЫ ДЛЯ СОЗДАНИЯ/УПРАВЛЕНИЯ ГРУППОЙ ОСТАЮТСЯ, если нужны!
@router.post("/", response_model=GroupOut)
def create_group(group: GroupCreate, db: Session = Depends(get_db)):
    db_group = Group(name=group.name, description=group.description, owner_id=group.owner_id)
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    return db_group

@router.get("/", response_model=List[GroupOut])
def get_groups(db: Session = Depends(get_db)):
    return db.query(Group).all()

@router.get("/user/{user_id}")
def get_groups_for_user(user_id: int, db: Session = Depends(get_db)):
    from src.models.group_member import GroupMember
    group_ids = db.query(GroupMember.group_id).filter(GroupMember.user_id == user_id).subquery()
    groups = db.query(Group).filter(Group.id.in_(group_ids)).all()
    # Добавляем количество участников для каждой группы
    result = []
    for group in groups:
        members = db.query(GroupMember).filter(GroupMember.group_id == group.id).all()
        member_ids = set([m.user_id for m in members])
        member_ids.add(group.owner_id)
        result.append({
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "owner_id": group.owner_id,
            "members_count": len(member_ids)
        })
    return result

@router.get("/{group_id}/detail/", response_model=GroupOut)
def group_detail(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    return group
