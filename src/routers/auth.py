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
import time

router = APIRouter()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")  # Настрой в amvera секрет!

def check_telegram_auth(init_data: str, bot_token: str) -> dict:
    """
    Проверка подписи Telegram WebApp (официальная логика)
    """
    print("[check_telegram_auth] start")
    print("init_data:", init_data)
    print("bot_token:", repr(bot_token))

    # Парсим initData как query string
    params = urllib.parse.parse_qs(init_data, keep_blank_values=True)
    print("parsed:", params)

    hash_from_telegram = params.pop("hash", [None])[0]
    if not hash_from_telegram:
        print("Нет параметра hash!")
        raise HTTPException(401, "Hash отсутствует")

    # WARNING: Удаляем signature если есть (не должен быть в data_check_string)
    if "signature" in params:
        print("WARNING: signature не должен быть в initData, удаляем")
        params.pop("signature")

    # Формируем data_check_string по правилам Telegram (сортируем ключи!)
    data_check_string = "\n".join(f"{k}={v[0]}" for k, v in sorted(params.items()))
    print("data_check_string:")
    print(data_check_string)

    # Секретный ключ: SHA256(bot_token)
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    print("calculated_hash:", calculated_hash)
    print("hash_from_telegram:", hash_from_telegram)

    if not hmac.compare_digest(calculated_hash, hash_from_telegram):
        print("❌ Подпись не совпадает!")
        raise HTTPException(401, "Неверная подпись Telegram WebApp (initData)")

    print("✅ Подпись совпадает!")
    return params

@router.post("/telegram", response_model=UserOut)
async def auth_via_telegram(request: Request, db: Session = Depends(get_db)):
    """
    Эндпоинт для аутентификации через Telegram Mini App.
    Получает initData, проверяет подпись, сохраняет пользователя в БД, возвращает UserOut.
    """
    data = await request.json()
    init_data = data.get("initData")
    print("[/api/auth/telegram] initData =", init_data)

    if not init_data:
        raise HTTPException(400, "initData не передан")

    params = check_telegram_auth(init_data, TELEGRAM_BOT_TOKEN)

    # Можно добавить проверку свежести initData по auth_date (например, не старше 1 минуты)
    auth_date = int(params.get("auth_date", [0])[0])
    if abs(time.time() - auth_date) > 60*5:
        raise HTTPException(401, "initData слишком старый. Перезапустите Mini App.")

    # user хранится как JSON-строка в параметре user
    user_raw = params.get("user", [None])[0]
    if not user_raw:
        raise HTTPException(400, "user отсутствует в initData")
    import json
    user_json = json.loads(user_raw)

    telegram_id = user_json["id"]
    first_name = user_json.get("first_name")
    last_name = user_json.get("last_name")
    username = user_json.get("username")
    photo_url = user_json.get("photo_url")
    language_code = user_json.get("language_code")
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
