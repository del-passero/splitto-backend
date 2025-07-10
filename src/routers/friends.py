# src/routers/friends.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from src.db import get_db
from src.models.friend import Friend
from src.models.user import User
from src.schemas.friend import FriendCreate, FriendOut
from src.schemas.user import UserOut

router = APIRouter()

def get_full_user(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"Пользователь {user_id} не найден")
    return user

@router.get("/list", response_model=List[FriendOut])
def get_friends_list(
    current_user_id: int,  # см. как получать user_id в Depends!
    db: Session = Depends(get_db)
):
    """
    Возвращает список всех друзей текущего пользователя.
    """
    friends = db.query(Friend)\
        .filter(Friend.user_id == current_user_id)\
        .options(joinedload(Friend.friend)).all()
    result = []
    for fr in friends:
        user_obj = get_full_user(db, fr.user_id)
        friend_obj = get_full_user(db, fr.friend_id)
        result.append(FriendOut(
            id=fr.id,
            user_id=fr.user_id,
            friend_id=fr.friend_id,
            created_at=fr.created_at,
            updated_at=fr.updated_at,
            user=UserOut.from_orm(user_obj),
            friend=UserOut.from_orm(friend_obj),
        ))
    return result

@router.post("/add", response_model=FriendOut)
def add_friend(
    friend: FriendCreate,
    db: Session = Depends(get_db),
    via_invite: Optional[bool] = False
):
    """
    Двустороннее добавление друга: оба сразу становятся друг у друга в друзьях.
    Если уже есть — ничего не делать.
    Если via_invite=True — инкрементируем invited_friends_count у пригласившего.
    """
    if friend.user_id == friend.friend_id:
        raise HTTPException(status_code=400, detail="Нельзя добавить самого себя")

    def ensure_friendship(a, b):
        exists = db.query(Friend).filter(
            Friend.user_id == a,
            Friend.friend_id == b
        ).first()
        if not exists:
            fr = Friend(user_id=a, friend_id=b)
            db.add(fr)
            db.flush()
            return fr
        return exists

    fr1 = ensure_friendship(friend.user_id, friend.friend_id)
    fr2 = ensure_friendship(friend.friend_id, friend.user_id)

    # --- КЛЮЧЕВОЕ: инкремент invited_friends_count, если добавление по инвайту ---
    if via_invite:
        inviter = db.query(User).filter(User.id == friend.friend_id).first()
        if inviter:
            inviter.invited_friends_count += 1
            db.add(inviter)
    db.commit()
    db.refresh(fr1)
    db.refresh(fr2)
    return FriendOut(
        id=fr1.id,
        user_id=fr1.user_id,
        friend_id=fr1.friend_id,
        created_at=fr1.created_at,
        updated_at=fr1.updated_at,
        user=UserOut.from_orm(get_full_user(db, fr1.user_id)),
        friend=UserOut.from_orm(get_full_user(db, fr1.friend_id)),
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
