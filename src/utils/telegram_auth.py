# src/utils/telegram_auth.py

import hashlib
import hmac
import urllib.parse
import os
from fastapi import Header, HTTPException, Depends, Request

from sqlalchemy.orm import Session
from src.db import get_db
from src.models.user import User

# Секретный ключ Telegram-бота, обязательно укажи его в .env
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

def parse_telegram_init_data(init_data: str) -> dict:
    """
    Проверяет подпись Telegram WebApp и возвращает разобранные поля.
    """
    if not init_data:
        raise HTTPException(status_code=401, detail="initData is required (Telegram WebApp Auth)")
    parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
    hash_from_telegram = parsed.pop('hash', None)
    if not hash_from_telegram:
        raise HTTPException(status_code=401, detail="No hash in initData (Telegram WebApp Auth)")
    data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, hash_from_telegram):
        raise HTTPException(401, detail="Invalid Telegram WebApp initData signature")
    return parsed

async def get_current_telegram_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    FastAPI Depends: получает текущего пользователя через Telegram initData.
    Фронт должен слать в каждый запрос JSON поле 'initData' или заголовок 'X-Telegram-InitData'.
    """
    # Получаем initData из body или заголовка
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

    parsed = parse_telegram_init_data(init_data)
    telegram_id = int(parsed.get("user[id]"))
    user = db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user:
        raise HTTPException(401, detail="Пользователь не зарегистрирован")
    return user
