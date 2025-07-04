from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session
from src.db import get_db
from src.models.user import User
from src.schemas.user import UserOut
import hashlib
import hmac
import urllib.parse
import os
import json

router = APIRouter()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7924065368:AAEXitusSdortU0C1yqLVmkU_yv4uZ_yI9Q")

def check_telegram_auth(init_data: str, bot_token: str) -> dict:
    req_data = urllib.parse.parse_qs(init_data, keep_blank_values=True)
    
    if 'hash' not in req_data:  # ← ИСПРАВЛЕНО: req_data, а не req_
        raise HTTPException(status_code=401, detail="Нет hash в initData")
    hash_from_telegram = req_data.pop('hash')[0]

    data_check_string = '\n'.join(f"{k}={v[0]}" for k, v in sorted(req_data.items()))
    
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, hash_from_telegram):
        raise HTTPException(status_code=401, detail="Неверная подпись Telegram WebApp")
    
    return req_data

@router.post("/telegram", response_model=UserOut)
async def auth_via_telegram(
    initData: str = Form(...),  # Получаем как form-data
    db: Session = Depends(get_db)
):
    parsed = check_telegram_auth(initData, TELEGRAM_BOT_TOKEN)

    user_raw = parsed.get('user', [''])[0]
    try:
        user_json = urllib.parse.unquote(user_raw)
        user = json.loads(user_json)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка парсинга user: {e}")

    telegram_id = int(user.get("id"))
    first_name = user.get("first_name")
    last_name = user.get("last_name")
    username = user.get("username")
    photo_url = user.get("photo_url")
    language_code = user.get("language_code")
    name = f"{first_name} {last_name}" if first_name and last_name else username or f"User {telegram_id}"

    user_obj = db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user_obj:
        user_obj = User(
            name=name,
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            photo_url=photo_url,
            language_code=language_code,
        )
        db.add(user_obj)
        db.commit()
        db.refresh(user_obj)
    else:
        user_obj.first_name = first_name
        user_obj.last_name = last_name
        user_obj.username = username
        user_obj.photo_url = photo_url
        user_obj.language_code = language_code
        db.commit()
        db.refresh(user_obj)

    return {
        "id": user_obj.id,
        "telegram_id": user_obj.telegram_id,
        "name": user_obj.name,
        "username": user_obj.username,
        "photo_url": user_obj.photo_url
    }