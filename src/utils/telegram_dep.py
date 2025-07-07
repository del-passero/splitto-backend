# splitto/backend/src/utils/telegram_dep.py

"""
Универсальная зависимость FastAPI для авторизации через Telegram WebApp initData,
использующая telegram-webapp-auth (TelegramAuthenticator).
Возвращает объект User из базы по валидации initData.
"""

import os
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.db import get_db
from src.models.user import User
from telegram_webapp_auth.auth import TelegramAuthenticator, generate_secret_key

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
_secret = generate_secret_key(TELEGRAM_BOT_TOKEN)
authenticator = TelegramAuthenticator(_secret)

async def get_current_telegram_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Зависимость для FastAPI — получает текущего пользователя через initData.
    Валидирует initData через telegram-webapp-auth.
    Ищет пользователя в базе по telegram_id.
    """
    # Пытаемся получить initData из body (POST/PUT/PATCH) или из header (GET)
    init_data = None
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            body = await request.json()
            init_data = body.get("initData")
        except Exception:
            pass
    if not init_data:
        init_data = request.headers.get("x-telegram-initdata")
    if not init_data:
        raise HTTPException(401, detail="initData required in body or header (Telegram WebApp Auth)")

    # Валидируем initData через библиотеку (TelegramAuthenticator)
    try:
        result = authenticator.validate(init_data)
    except Exception as e:
        raise HTTPException(401, detail=f"Ошибка авторизации: {str(e)}")

    # Извлекаем telegram_id из валидированного initData (dataclass WebAppUser)
    user_data = result.user
    telegram_id = user_data.id

    # Находим пользователя в базе
    user = db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user:
        raise HTTPException(401, detail="Пользователь не зарегистрирован")
    return user
