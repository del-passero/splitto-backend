# src/routers/auth.py

from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session
from src.db import get_db
from src.models.user import User
from src.schemas.user import UserOut
from src.utils.user import get_display_name
import hashlib
import hmac
import os
import urllib.parse
import json

router = APIRouter()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7924065368:AAEXitusSdortU0C1yqLVmkU_yv4uZ_yI9Q")

def check_telegram_auth(init_data: str, bot_token: str) -> dict:
    print("=== [check_telegram_auth] start ===")
    print("init_data:", init_data)
    print("bot_token:", repr(bot_token))

    # Парсим init_data как key=value (без decode!)
    parsed = []
    hash_from_telegram = None
    for item in init_data.split('&'):
        k, v = item.split('=', 1)
        if k == 'hash':
            hash_from_telegram = v
        elif k == 'signature':
            print("WARNING: signature не нужен — пропускаем")
        else:
            parsed.append((k, v))
    if not hash_from_telegram:
        raise HTTPException(401, "Нет параметра hash в initData!")

    # Строго сортируем по ключу (ключ=значение, значения — как есть!)
    parsed.sort(key=lambda x: x[0])
    data_check_string = '\n'.join(f"{k}={v}" for k, v in parsed)
    print("data_check_string:\n", data_check_string)

    # Считаем hash через HMAC-SHA256 c ключом SHA256(bot_token)
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    print("calculated_hash:", calculated_hash)
    print("hash_from_telegram:", hash_from_telegram)

    if not hmac.compare_digest(calculated_hash, hash_from_telegram):
        print("❌ Подпись не совпадает!")
        raise HTTPException(401, "Неверная подпись Telegram WebApp (initData)")

    print("✅ Подпись совпадает!")
    # Возвращаем dict из оригинальных ключей
    return {k: v for k, v in parsed}

@router.post("/telegram", response_model=UserOut)
async def auth_via_telegram(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    init_data = data.get("initData")
    print(f"[/api/auth/telegram] initData = {init_data}")
    if not init_data:
        raise HTTPException(400, "initData is required")

    parsed = check_telegram_auth(init_data, TELEGRAM_BOT_TOKEN)
    # user — строка, парсим только после валидации
    user_str = urllib.parse.unquote(parsed.get("user"))
    user_obj = json.loads(user_str)

    telegram_id = int(user_obj["id"])
    first_name = user_obj.get("first_name")
    last_name = user_obj.get("last_name")
    username = user_obj.get("username")
    photo_url = user_obj.get("photo_url")
    language_code = user_obj.get("language_code")
    name = get_display_name(first_name, last_name, username, telegram_id)

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
