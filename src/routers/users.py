# src/routers/users.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import cast, String, or_
from src.models.user import User
from src.schemas.user import UserCreate, UserOut
from src.db import get_db
from typing import List, Optional

router = APIRouter()

@router.post("/", response_model=UserOut)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """
    Создать нового пользователя со всеми возможными полями Telegram.
    """
    db_user = User(
        name=user.name,
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

@router.get("/search", response_model=List[UserOut])
def search_users(
    q: str = Query(..., min_length=2),
    exclude_user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Поиск пользователей по имени, username или telegram_id (или другим полям).
    exclude_user_id — чтобы не искать самого себя.
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
    return query.limit(15).all()

@router.get("/", response_model=List[UserOut])
def get_users(db: Session = Depends(get_db)):
    return db.query(User).all()

@router.get("/{user_id}", response_model=UserOut)
def get_user_by_id(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user
