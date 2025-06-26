# src/routers/users.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import cast, String, or_
from src.models.user import User
from src.schemas.user import UserCreate, UserOut
from src.db import get_db
from typing import List, Optional
from src.utils.user import get_display_name
from src.utils.telegram_auth import get_current_telegram_user

router = APIRouter()

@router.post("/", response_model=UserOut)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """
    Создать нового пользователя. Поле name всегда first_name + last_name (или username, если нет).
    """
    display_name = get_display_name(
        first_name=getattr(user, "first_name", ""),
        last_name=getattr(user, "last_name", ""),
        username=getattr(user, "username", ""),
        telegram_id=getattr(user, "telegram_id", None)
    )
    db_user = User(
        name=display_name,
        telegram_id=user.telegram_id,
        username=getattr(user, "username", None),
        first_name=getattr(user, "first_name", None),
        last_name=getattr(user, "last_name", None),
        photo_url=getattr(user, "photo_url", None),
        language_code=getattr(user, "language_code", None),
        allows_write_to_pm=getattr(user, "allows_write_to_pm", True),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_telegram_user)):
    """
    Возвращает данные текущего пользователя через Telegram WebApp initData.
    """
    # name всегда в правильном формате
    current_user.name = get_display_name(
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        username=current_user.username,
        telegram_id=current_user.telegram_id
    )
    return current_user

@router.get("/search", response_model=List[UserOut])
def search_users(
    q: str = Query(..., min_length=2),
    exclude_user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Поиск пользователей по имени, username или telegram_id.
    """
    query = db.query(User).filter(
        or_(
            User.name.ilike(f"%{q}%"),
            User.username.ilike(f"%{q}%"),
            User.first_name.ilike(f"%{q}%"),
            User.last_name.ilike(f"%{q}%"),
            cast(User.telegram_id, String).ilike(f"%{q}%"),
        )
    )
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    users = query.limit(15).all()
    for user in users:
        user.name = get_display_name(
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            telegram_id=user.telegram_id
        )
    return users

@router.get("/", response_model=List[UserOut])
def get_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    for user in users:
        user.name = get_display_name(
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            telegram_id=user.telegram_id
        )
    return users

@router.get("/{user_id}", response_model=UserOut)
def get_user_by_id(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.name = get_display_name(
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        telegram_id=user.telegram_id
    )
    return user
