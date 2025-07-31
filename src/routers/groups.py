# src/routers/groups.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List
import secrets

from src.db import get_db
from src.models.group import Group
from src.models.group_member import GroupMember
from src.models.group_invite import GroupInvite
from src.models.user import User
from src.models.transaction import Transaction
from src.schemas.group import GroupCreate, GroupOut
from src.schemas.group_invite import GroupInviteOut
from src.utils.balance import calculate_group_balances, greedy_settle_up
from src.schemas.settlement import SettlementOut
from src.utils.telegram_dep import get_current_telegram_user

router = APIRouter()

# =====================
# Вспомогательные функции для работы с группами
# =====================

def get_group_or_404(db: Session, group_id: int) -> Group:
    # Возвращает объект Group по id. Если не найдено — вызывает 404.
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    return group

def get_group_member_ids(db: Session, group_id: int) -> List[int]:
    # Возвращает список user_id всех участников конкретной группы (owner_id здесь уже всегда добавлен в таблицу участников!)
    member_ids = [m.user_id for m in db.query(GroupMember).filter(GroupMember.group_id == group_id).all()]
    return member_ids

def get_group_transactions(db: Session, group_id: int) -> List[Transaction]:
    # Возвращает все транзакции по данной группе, исключая удалённые. Применяет joinedload для оптимизации подгрузки связей (shares).
    return db.query(Transaction)\
        .filter(Transaction.group_id == group_id, Transaction.is_deleted == False)\
        .options(joinedload(Transaction.shares)).all()

def add_member_to_group(db: Session, group_id: int, user_id: int):
    # Универсальная функция для добавления участника в группу.
    # Если пользователь уже есть в группе, повторно не добавляется.
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
    """
    Возвращает net balance (итоговый баланс по долгам) для каждого участника конкретной группы.
    Формирует список из user_id и соответствующих балансов.
    """
    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)
    net_balance = calculate_group_balances(transactions, member_ids)
    return [
        {"user_id": uid, "balance": round(balance, 2)}
        for uid, balance in net_balance.items()
    ]

@router.get("/{group_id}/settle-up", response_model=List[SettlementOut])
def get_group_settle_up(group_id: int, db: Session = Depends(get_db)):
    """
    Возвращает оптимальный (жадный) список переводов между участниками группы,
    чтобы погасить все долги минимальным количеством переводов.
    """
    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)
    net_balance = calculate_group_balances(transactions, member_ids)
    settlements = greedy_settle_up(net_balance)
    return settlements

@router.post("/", response_model=GroupOut)
def create_group(group: GroupCreate, db: Session = Depends(get_db)):
    """
    Создать новую группу. После создания автоматически добавить владельца (owner_id) в участники этой группы.
    Владелец группы всегда считается полноценным участником.
    """
    # Сначала создаём саму группу (запись в таблице groups)
    db_group = Group(name=group.name, description=group.description, owner_id=group.owner_id)
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    # Затем добавляем владельца как участника (запись в таблицу group_members). Гарантируем, что owner_id всегда будет среди участников.
    add_member_to_group(db, db_group.id, db_group.owner_id)
    return db_group

@router.get("/", response_model=List[GroupOut])
def get_groups(db: Session = Depends(get_db)):
    """
    Получить список всех существующих групп (без фильтрации по пользователю).
    """
    return db.query(Group).all()

@router.get("/user/{user_id}")
def get_groups_for_user(user_id: int, db: Session = Depends(get_db)):
    """
    Получить список всех групп, в которых состоит указанный пользователь (user_id).
    Для каждой группы возвращается количество участников (members_count), которое считается по таблице group_members.
    """
    group_ids = db.query(GroupMember.group_id).filter(GroupMember.user_id == user_id).subquery()
    groups = db.query(Group).filter(Group.id.in_(group_ids)).all()
    result = []
    for group in groups:
        members = db.query(GroupMember).filter(GroupMember.group_id == group.id).all()
        member_ids = set([m.user_id for m in members])
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
    # ЯВНО ПОДГРУЖАЕМ УЧАСТНИКОВ!!!
    group.members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    return group



# =====================
# Роуты для управления инвайтами (приглашениями) в группу
# =====================

@router.post("/{group_id}/invite", response_model=GroupInviteOut)
def create_group_invite(group_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_telegram_user)):
    """
    Создать (или вернуть существующий) инвайт для приглашения в группу.
    Если инвайт для этой группы уже существует, возвращает его; если нет — создаёт новый токен.
    """
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
    """
    Принять инвайт в группу по токену приглашения.
    Если пользователь ещё не состоит в группе, он добавляется как участник (в group_members).
    """
    invite = db.query(GroupInvite).filter(GroupInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Инвайт не найден")
    group_id = invite.group_id
    add_member_to_group(db, group_id, current_user.id)
    return {"detail": "Успешно добавлен в группу"}
