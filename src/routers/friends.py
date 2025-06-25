# src/routers/friends.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from src.db import get_db
from src.models.friend import Friend
from src.models.user import User
from src.models.transaction import Transaction
from src.schemas.friend import FriendCreate, FriendOut
from src.schemas.user import UserOut
from src.utils.balance import calculate_global_balance

router = APIRouter()

# =========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================

def get_full_user(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"Пользователь {user_id} не найден")
    return user

def get_transactions_between_users(db: Session, user_id: int, friend_id: int) -> List[Transaction]:
    # Возвращает все транзакции, где оба пользователя участвуют (в любой роли)
    return db.query(Transaction).filter(
        Transaction.is_deleted == False,
        (
            (Transaction.paid_by == user_id) | (Transaction.paid_by == friend_id) |
            (Transaction.created_by == user_id) | (Transaction.created_by == friend_id) |
            (Transaction.transfer_from == user_id) | (Transaction.transfer_from == friend_id)
        )
    ).options(joinedload(Transaction.shares)).all()

# =========================
# ОСНОВНЫЕ РОУТЫ
# =========================

@router.get("/list", response_model=List[FriendOut])
def get_friends_list(
    current_user_id: int,  # см. как получать user_id в Depends!
    db: Session = Depends(get_db)
):
    """
    Возвращает список друзей с полной инфой и балансом.
    """
    # Все связи accepted, где текущий пользователь инициатор
    friends = db.query(Friend)\
        .filter(Friend.user_id == current_user_id, Friend.status == "accepted")\
        .options(joinedload(Friend.friend)).all()
    
    result = []
    for fr in friends:
        # Полная инфа о friend
        user_obj = get_full_user(db, fr.user_id)
        friend_obj = get_full_user(db, fr.friend_id)
        # Все общие транзакции между пользователями (во всех группах)
        transactions = get_transactions_between_users(db, fr.user_id, fr.friend_id)
        # Расчёт баланса между пользователями
        balance = calculate_global_balance(transactions, fr.user_id, fr.friend_id)
        # Баланс для UI (positive = plus, negative = minus, zero = zero)
        if abs(balance) < 1e-2:
            balance_type = "zero"
        elif balance > 0:
            balance_type = "plus"
        else:
            balance_type = "minus"
        result.append(FriendOut(
            id=fr.id,
            user_id=fr.user_id,
            friend_id=fr.friend_id,
            status=fr.status,
            created_at=fr.created_at,
            updated_at=fr.updated_at,
            user=UserOut.from_orm(user_obj),
            friend=UserOut.from_orm(friend_obj),
            balance=abs(balance),
            balance_type=balance_type
        ))
    return result

@router.get("/requests/incoming", response_model=List[FriendOut])
def get_incoming_requests(
    current_user_id: int,
    db: Session = Depends(get_db)
):
    """
    Входящие заявки в друзья (friend_id = текущий пользователь, status = pending)
    """
    requests = db.query(Friend)\
        .filter(Friend.friend_id == current_user_id, Friend.status == "pending")\
        .all()
    return [
        FriendOut(
            id=req.id,
            user_id=req.user_id,
            friend_id=req.friend_id,
            status=req.status,
            created_at=req.created_at,
            updated_at=req.updated_at,
            user=UserOut.from_orm(get_full_user(db, req.user_id)),
            friend=UserOut.from_orm(get_full_user(db, req.friend_id)),
            balance=0,
            balance_type="zero"
        )
        for req in requests
    ]

@router.get("/requests/outgoing", response_model=List[FriendOut])
def get_outgoing_requests(
    current_user_id: int,
    db: Session = Depends(get_db)
):
    """
    Исходящие заявки в друзья (user_id = текущий пользователь, status = pending)
    """
    requests = db.query(Friend)\
        .filter(Friend.user_id == current_user_id, Friend.status == "pending")\
        .all()
    return [
        FriendOut(
            id=req.id,
            user_id=req.user_id,
            friend_id=req.friend_id,
            status=req.status,
            created_at=req.created_at,
            updated_at=req.updated_at,
            user=UserOut.from_orm(get_full_user(db, req.user_id)),
            friend=UserOut.from_orm(get_full_user(db, req.friend_id)),
            balance=0,
            balance_type="zero"
        )
        for req in requests
    ]

@router.get("/requests/blocked", response_model=List[FriendOut])
def get_blocked_friends(
    current_user_id: int,
    db: Session = Depends(get_db)
):
    """
    Блокированные пользователи (user_id = текущий, status = blocked)
    """
    blocks = db.query(Friend)\
        .filter(Friend.user_id == current_user_id, Friend.status == "blocked")\
        .all()
    return [
        FriendOut(
            id=bl.id,
            user_id=bl.user_id,
            friend_id=bl.friend_id,
            status=bl.status,
            created_at=bl.created_at,
            updated_at=bl.updated_at,
            user=UserOut.from_orm(get_full_user(db, bl.user_id)),
            friend=UserOut.from_orm(get_full_user(db, bl.friend_id)),
            balance=0,
            balance_type="zero"
        )
        for bl in blocks
    ]

@router.post("/request", response_model=FriendOut)
def send_friend_request(
    friend: FriendCreate,
    db: Session = Depends(get_db)
):
    """
    Отправить заявку в друзья (user_id -> friend_id, статус = pending)
    """
    if friend.user_id == friend.friend_id:
        raise HTTPException(status_code=400, detail="Нельзя добавить самого себя")
    # Проверяем, нет ли уже связи
    exists = db.query(Friend).filter(
        Friend.user_id == friend.user_id,
        Friend.friend_id == friend.friend_id
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Запрос уже отправлен или вы уже друзья")
    # Проверяем, что оба пользователя существуют
    user_obj = get_full_user(db, friend.user_id)
    friend_obj = get_full_user(db, friend.friend_id)
    # Создаём связь
    new_req = Friend(
        user_id=friend.user_id,
        friend_id=friend.friend_id,
        status="pending"
    )
    db.add(new_req)
    db.commit()
    db.refresh(new_req)
    return FriendOut(
        id=new_req.id,
        user_id=new_req.user_id,
        friend_id=new_req.friend_id,
        status=new_req.status,
        created_at=new_req.created_at,
        updated_at=new_req.updated_at,
        user=UserOut.from_orm(user_obj),
        friend=UserOut.from_orm(friend_obj),
        balance=0,
        balance_type="zero"
    )

@router.post("/accept", response_model=FriendOut)
def accept_friend_request(
    request_id: int,
    db: Session = Depends(get_db)
):
    """
    Принять входящий запрос в друзья.
    """
    req = db.query(Friend).filter(Friend.id == request_id, Friend.status == "pending").first()
    if not req:
        raise HTTPException(status_code=404, detail="Заявка не найдена или уже обработана")
    req.status = "accepted"
    db.add(req)
    # Создаём зеркальную связь (accepted)
    back = db.query(Friend).filter(
        Friend.user_id == req.friend_id,
        Friend.friend_id == req.user_id
    ).first()
    if back:
        back.status = "accepted"
        db.add(back)
    else:
        db.add(Friend(
            user_id=req.friend_id,
            friend_id=req.user_id,
            status="accepted"
        ))
    db.commit()
    db.refresh(req)
    return FriendOut(
        id=req.id,
        user_id=req.user_id,
        friend_id=req.friend_id,
        status=req.status,
        created_at=req.created_at,
        updated_at=req.updated_at,
        user=UserOut.from_orm(get_full_user(db, req.user_id)),
        friend=UserOut.from_orm(get_full_user(db, req.friend_id)),
        balance=0,
        balance_type="zero"
    )

@router.post("/decline", response_model=FriendOut)
def decline_friend_request(
    request_id: int,
    db: Session = Depends(get_db)
):
    """
    Отклонить входящий запрос в друзья (удалить связь).
    """
    req = db.query(Friend).filter(Friend.id == request_id, Friend.status == "pending").first()
    if not req:
        raise HTTPException(status_code=404, detail="Заявка не найдена или уже обработана")
    db.delete(req)
    db.commit()
    return FriendOut(
        id=req.id,
        user_id=req.user_id,
        friend_id=req.friend_id,
        status="declined",
        created_at=req.created_at,
        updated_at=req.updated_at,
        user=UserOut.from_orm(get_full_user(db, req.user_id)),
        friend=UserOut.from_orm(get_full_user(db, req.friend_id)),
        balance=0,
        balance_type="zero"
    )

@router.delete("/remove", status_code=204)
def remove_friend(
    user_id: int,
    friend_id: int,
    db: Session = Depends(get_db)
):
    """
    Удалить друга двусторонне (удаляет обе связи).
    """
    db.query(Friend).filter(
        (Friend.user_id == user_id) & (Friend.friend_id == friend_id)
    ).delete()
    db.query(Friend).filter(
        (Friend.user_id == friend_id) & (Friend.friend_id == user_id)
    ).delete()
    db.commit()
    return

@router.post("/block", response_model=FriendOut)
def block_friend(
    user_id: int,
    friend_id: int,
    db: Session = Depends(get_db)
):
    """
    Заблокировать пользователя (или обновить статус, если уже есть связь).
    """
    rel = db.query(Friend).filter(
        Friend.user_id == user_id,
        Friend.friend_id == friend_id
    ).first()
    if rel:
        rel.status = "blocked"
        db.add(rel)
    else:
        rel = Friend(user_id=user_id, friend_id=friend_id, status="blocked")
        db.add(rel)
    db.commit()
    db.refresh(rel)
    return FriendOut(
        id=rel.id,
        user_id=rel.user_id,
        friend_id=rel.friend_id,
        status=rel.status,
        created_at=rel.created_at,
        updated_at=rel.updated_at,
        user=UserOut.from_orm(get_full_user(db, rel.user_id)),
        friend=UserOut.from_orm(get_full_user(db, rel.friend_id)),
        balance=0,
        balance_type="zero"
    )

@router.post("/unblock", response_model=FriendOut)
def unblock_friend(
    user_id: int,
    friend_id: int,
    db: Session = Depends(get_db)
):
    """
    Разблокировать пользователя (удалить блокирующую связь).
    """
    rel = db.query(Friend).filter(
        Friend.user_id == user_id,
        Friend.friend_id == friend_id,
        Friend.status == "blocked"
    ).first()
    if rel:
        db.delete(rel)
        db.commit()
    return FriendOut(
        id=rel.id,
        user_id=rel.user_id,
        friend_id=rel.friend_id,
        status="unblocked",
        created_at=rel.created_at,
        updated_at=rel.updated_at,
        user=UserOut.from_orm(get_full_user(db, rel.user_id)),
        friend=UserOut.from_orm(get_full_user(db, rel.friend_id)),
        balance=0,
        balance_type="zero"
    )
