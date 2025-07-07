# splitto/backend/src/routers/auth.py

"""
Роутер авторизации через Telegram WebApp.
Использует telegram-webapp-auth (класс TelegramAuthenticator).
Валидирует initData, создаёт или обновляет пользователя в базе.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session
from src.db import get_db
from src.models.user import User
from src.schemas.user import UserOut
from src.utils.user import get_display_name
import os

from telegram_webapp_auth.auth import TelegramAuthenticator, generate_secret_key

router = APIRouter()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
_secret = generate_secret_key(TELEGRAM_BOT_TOKEN)
authenticator = TelegramAuthenticator(_secret)

@router.post("/telegram", response_model=UserOut)
async def auth_via_telegram(request: Request, db: Session = Depends(get_db)):
    """
    Авторизация пользователя через Telegram WebApp.
    Получаем initData, валидируем через telegram-webapp-auth,
    сохраняем (или обновляем) пользователя в базе.
    """
    data = await request.json()
    init_data = data.get("initData")
    if not init_data:
        raise HTTPException(400, "initData is required")

    # ВАЛИДАЦИЯ через библиотеку!
    try:
        result = authenticator.validate(init_data)
    except Exception as e:
        raise HTTPException(401, f"Ошибка авторизации: {str(e)}")

    # user_data — dataclass WebAppUser, доступен как .id, .username и т.д.
    user_data = result.user

    telegram_id = user_data.id
    first_name = user_data.first_name
    last_name = getattr(user_data, "last_name", None)
    username = getattr(user_data, "username", None)
    photo_url = getattr(user_data, "photo_url", None)
    language_code = getattr(user_data, "language_code", None)
    name = get_display_name(first_name, last_name, username, telegram_id)

    # Сохраняем или обновляем пользователя
    user = db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user:
        user = User(
            name=name,
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            photo_url=photo_url,
            language_code=language_code,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.first_name = first_name
        user.last_name = last_name
        user.username = username
        user.photo_url = photo_url
        user.language_code = language_code
        user.name = name
        db.commit()
        db.refresh(user)
    return user
