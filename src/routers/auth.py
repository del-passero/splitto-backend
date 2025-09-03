# splitto/backend/src/routers/auth.py
"""
Роутер авторизации через Telegram WebApp.
Валидирует initData, создаёт (если нет) или лениво обновляет пользователя и возвращает его.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session

from src.db import get_db
from src.schemas.user import UserOut
from src.models.user import User
from src.utils.telegram_dep import validate_and_sync_user

router = APIRouter()


@router.post("/telegram", response_model=UserOut)
async def auth_via_telegram(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Точка входа для фронта (/api/auth/telegram).
    Обязательно принимает JSON: { "initData": "<строка из Telegram.WebApp.initData>" }
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    init_data = (data or {}).get("initData")
    if not init_data:
        raise HTTPException(status_code=400, detail="initData is required")

    # Создаём пользователя при первом входе, иначе лениво обновляем профиль (включая language_code).
    user = validate_and_sync_user(init_data, db, create_if_missing=True)
    return user
