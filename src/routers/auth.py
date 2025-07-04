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

router = APIRouter()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN")


def check_telegram_auth(init_data: str, bot_token: str) -> dict:
    print("[check_telegram_auth] start")
    print(f"init_data: {init_data}")
    print(f"bot_token: '{bot_token}'")

    # Парсим параметры, НЕ декодируем значения!
    req_data = urllib.parse.parse_qs(init_data, keep_blank_values=True)
    print("parsed:", req_data)

    # hash нужно отделить
    if 'hash' not in req_data:
        print("Нет параметра hash!")
        raise HTTPException(401, "Нет hash в initData")
    hash_from_telegram = req_data.pop('hash')[0]

    # signature не должен быть, но если есть — удаляем
    if 'signature' in req_data:
        print("WARNING: signature не должен быть в initData, удаляем")
        req_data.pop('signature')

    # Собираем data_check_string (url-encoded значения!)
    data_check_string = '\n'.join(f"{k}={v[0]}" for k, v in sorted(req_data.items()))
    print("data_check_string:\n", data_check_string)

    # Ключ — SHA256(bot_token)
    secret_key = hashlib.sha256(bot_token.encode()).digest()

    # Считаем подпись
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    print("calculated_hash:", calculated_hash)
    print("hash_from_telegram:", hash_from_telegram)

    if not hmac.compare_digest(calculated_hash, hash_from_telegram):
        print("❌ Подпись не совпадает!")
        raise HTTPException(401, "Неверная подпись Telegram WebApp (initData)")
    print("✅ Подпись совпала!")

    # Возвращаем исходные параметры (все url-encoded!)
    return req_data


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

    # Парсим user (это url-encoded json string)
    user_raw = parsed.get('user')[0]
    user_json = urllib.parse.unquote(user_raw)
    user = eval(user_json)  # или json.loads(user_json) если уверен, что строка безопасна

    telegram_id = int(user.get("id"))
    first_name = user.get("first_name")
    last_name = user.get("last_name")
    username = user.get("username")
    photo_url = user.get("photo_url")
    language_code = user.get("language_code")
    name = get_display_name(first_name, last_name, username, telegram_id)

    # Найти пользователя или создать
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
        # Обновляем данные
        user_obj.first_name = first_name
        user_obj.last_name = last_name
        user_obj.username = username
        user_obj.photo_url = photo_url
        user_obj.language_code = language_code
        user_obj.name = name
        db.commit()
        db.refresh(user_obj)
    return user_obj
