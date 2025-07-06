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
import json

router = APIRouter()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN")

def check_telegram_auth(init_data: str, bot_token: str) -> dict:
    print("[check_telegram_auth] start")
    print("init_data:", init_data)
    print("bot_token:", repr(bot_token))

    # 1. Ищем hash, signature удаляем, собираем пары
    pairs = []
    hash_from_telegram = None
    for item in init_data.split('&'):
        if item.startswith("hash="):
            hash_from_telegram = item[len("hash="):]
        elif item.startswith("signature="):
            print("WARNING: signature не должен быть в initData, удаляем")
            continue
        else:
            pairs.append(item)
    if not hash_from_telegram:
        print("❌ Нет параметра hash!")
        raise HTTPException(401, "Параметр hash не найден")

    # 2. Сортируем по ключу
    pairs_sorted = sorted(pairs, key=lambda x: x.split('=')[0])
    data_check_string = '\n'.join(pairs_sorted)
    print("data_check_string:\n" + data_check_string)

    # 3. Считаем подпись
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    print("calculated_hash:", calculated_hash)
    print("hash_from_telegram:", hash_from_telegram)
    if not hmac.compare_digest(calculated_hash, hash_from_telegram):
        print("❌ Подпись не совпадает!")
        raise HTTPException(401, "Неверная подпись Telegram WebApp (initData)")
    print("✅ Подпись совпала!")

    # Возвращаем пары как dict (строки! user — строка)
    parsed_dict = {}
    for pair in pairs_sorted:
        k, v = pair.split("=", 1)
        parsed_dict[k] = v
    return parsed_dict

@router.post("/telegram", response_model=UserOut)
async def auth_via_telegram(request: Request, db: Session = Depends(get_db)):
    """
    Аутентификация через Telegram WebApp. Принимает initData, проверяет подпись,
    создаёт/обновляет пользователя, возвращает UserOut.
    """
    data = await request.json()
    init_data = data.get("initData")
    print(f"[/api/auth/telegram] initData = {init_data}")
    if not init_data:
        raise HTTPException(400, "initData is required")
    parsed = check_telegram_auth(init_data, TELEGRAM_BOT_TOKEN)

    # Достаем user-строку и парсим только ПОСЛЕ проверки подписи
    user_raw = parsed.get("user")
    if not user_raw:
        raise HTTPException(400, "user missing in initData")
    user_json = json.loads(user_raw)

    telegram_id = int(user_json.get("id"))
    first_name = user_json.get("first_name")
    last_name = user_json.get("last_name")
    username = user_json.get("username")
    photo_url = user_json.get("photo_url")
    language_code = user_json.get("language_code")
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
