# src/routers/auth.py

from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session
from src.db import get_db
from src.models.user import User
from src.schemas.user import UserOut
from src.utils.user import get_display_name
import hashlib
import hmac
import json
import os

router = APIRouter()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN")

def check_telegram_auth(init_data: str, bot_token: str) -> dict:
    """
    Проверяет подпись Telegram WebApp.
    ВАЖНО: строку initData нельзя парсить или декодировать, она должна остаться в raw-форме!
    """
    print("[check_telegram_auth] start")
    print("init_data:", init_data)
    print("bot_token:", repr(bot_token))

    items = [item for item in init_data.split('&')]
    data_pairs = []
    hash_from_telegram = ""
    for item in items:
        if item.startswith("hash="):
            hash_from_telegram = item[len("hash="):]
        elif item.startswith("signature="):
            print("WARNING: signature не должен быть в initData, удаляем")
            continue
        else:
            data_pairs.append(item)
    data_pairs.sort(key=lambda s: s.split('=')[0])
    data_check_string = '\n'.join(data_pairs)

    print("data_check_string:\n" + data_check_string)

    secret_key = hashlib.sha256(bot_token.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    print("calculated_hash:", calculated_hash)
    print("hash_from_telegram:", hash_from_telegram)
    if not hmac.compare_digest(calculated_hash, hash_from_telegram):
        print("❌ Подпись не совпадает!")
        raise HTTPException(401, "Неверная подпись Telegram WebApp (initData)")
    print("✅ Подпись совпала!")

    # Формируем dict для возвращения в handler
    parsed_dict = {}
    for pair in data_pairs:
        key, value = pair.split("=", 1)
        parsed_dict[key] = value
    return parsed_dict

@router.post("/telegram", response_model=UserOut)
async def auth_via_telegram(request: Request, db: Session = Depends(get_db)):
    """
    Принимает {"initData": "..."} от фронта, валидирует, сохраняет пользователя.
    """
    data = await request.json()
    init_data = data.get("initData")
    print(f"[/api/auth/telegram] initData = {init_data}")
    if not init_data:
        raise HTTPException(400, "initData is required")
    parsed = check_telegram_auth(init_data, TELEGRAM_BOT_TOKEN)

    # Важно: user — строка в формате JSON
    user_data = json.loads(parsed["user"])
    telegram_id = int(user_data["id"])
    first_name = user_data.get("first_name", "")
    last_name = user_data.get("last_name", "")
    username = user_data.get("username", "")
    photo_url = user_data.get("photo_url", "")
    language_code = user_data.get("language_code", "")
    name = get_display_name(first_name, last_name, username, telegram_id)

    # Создаем/обновляем пользователя
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
