# src/routers/auth.py

from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session
from src.db import get_db
from src.models.user import User
from src.schemas.user import UserOut
from src.utils.user import get_display_name
import hashlib
import hmac
import urllib.parse
import os

# Вставляем сюда переменную окружения для Telegram Bot Token и лог
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN")
print("DEBUG | TELEGRAM_BOT_TOKEN:", repr(TELEGRAM_BOT_TOKEN))

router = APIRouter()

def check_telegram_auth(init_data: str, bot_token: str) -> dict:
    """
    Проверка подписи Telegram WebApp (официальная логика).
    """
    parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
    hash_from_telegram = parsed.pop('hash')
    data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    # Выводим всё, что важно для отладки
    print("DEBUG | check_telegram_auth")
    print("  init_data =", repr(init_data))
    print("  bot_token =", repr(bot_token))
    print("  data_check_string =", repr(data_check_string))
    print("  calculated_hash =", calculated_hash)
    print("  hash_from_telegram =", hash_from_telegram)

    if not hmac.compare_digest(calculated_hash, hash_from_telegram):
        print("  ❌ Подпись не совпадает!")
        raise HTTPException(401, "Неверная подпись Telegram WebApp (initData)")
    print("  ✅ Подпись ОК")
    return parsed

@router.post("/telegram", response_model=UserOut)
async def auth_via_telegram(request: Request, db: Session = Depends(get_db)):
    """
    Аутентификация через Telegram WebApp. Принимает initData, проверяет подпись,
    создаёт/обновляет пользователя, возвращает UserOut.
    """
    data = await request.json()
    init_data = data.get("initData")
    print("DEBUG | /api/auth/telegram | init_data =", repr(init_data))
    if not init_data:
        raise HTTPException(400, "initData is required")
    parsed = check_telegram_auth(init_data, TELEGRAM_BOT_TOKEN)

    def get_user_field(field: str):
        return parsed.get(f"user[{field}]")

    telegram_id = int(get_user_field("id"))
    first_name = get_user_field("first_name")
    last_name = get_user_field("last_name")
    username = get_user_field("username")
    photo_url = get_user_field("photo_url")
    language_code = get_user_field("language_code")
    # name всегда вычисляется по first_name + last_name + username + telegram_id
    name = get_display_name(first_name, last_name, username, telegram_id)

    # Найти пользователя или создать
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
        print(f"DEBUG | Новый пользователь создан: {user}")
    else:
        # Обновляем имя, если first_name или last_name поменялись
        user.first_name = first_name
        user.last_name = last_name
        user.username = username
        user.photo_url = photo_url
        user.language_code = language_code
        user.name = name  # Обновляем name!
        db.commit()
        db.refresh(user)
        print(f"DEBUG | Пользователь обновлён: {user}")
    return user
