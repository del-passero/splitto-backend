# splitto/backend/src/routers/users.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import cast, String, or_
from src.models.user import User
from src.schemas.user import UserCreate, UserOut
from src.db import get_db
from typing import List, Optional
from src.utils.user import get_display_name
from src.utils.telegram_dep import get_current_telegram_user  # <--- НОВЫЙ ИМПОРТ

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

# остальные роуты не меняем
