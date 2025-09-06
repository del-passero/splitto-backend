# splitto/backend/src/utils/telegram_dep.py
"""
Универсальные утилиты авторизации через Telegram WebApp initData.
- validate_and_sync_user: валидация initData + ленивое обновление полей пользователя в БД
- get_current_telegram_user: FastAPI-зависимость (не создаёт пользователя, только валидирует и обновляет)
"""

import os
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.db import get_db
from src.models.user import User
from src.utils.user import get_display_name
from telegram_webapp_auth.auth import TelegramAuthenticator, generate_secret_key

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

_auth_secret = generate_secret_key(TELEGRAM_BOT_TOKEN)
authenticator = TelegramAuthenticator(_auth_secret)


def _normalize_lang(code: Optional[str]) -> str:
    """
    Схлопываем код языка до {ru,en,es}.
    Если язык не пришёл (частый кейс для English) — используем 'en'.
    """
    if not code:
        return "en"
    c = code.lower()
    if "-" in c:
        c = c.split("-")[0]
    return c if c in {"ru", "en", "es"} else "en"


def _get_init_data_from_request(request: Request, body: Optional[dict]) -> Optional[str]:
    """
    Пытаемся достать initData:
      - из JSON body (ключ 'initData')
      - из заголовка 'x-telegram-initdata'
      - из query (?init_data=...)
    """
    if body and isinstance(body, dict):
        v = body.get("initData")
        if isinstance(v, str) and v.strip():
            return v

    header_v = request.headers.get("x-telegram-initdata") or request.headers.get("X-Telegram-InitData")
    if header_v:
        return header_v

    q = request.query_params.get("init_data")
    if q:
        return q

    return None


def _apply_user_fields_from_tg(u: User, tg_user) -> bool:
    """
    Копируем в User поля из Telegram-профиля. Возвращает True, если что-то изменилось.
    """
    changed = False

    def upd(field: str, new_val):
        nonlocal changed, u
        if getattr(u, field) != new_val:
            setattr(u, field, new_val)
            changed = True

    first_name = getattr(tg_user, "first_name", None)
    last_name = getattr(tg_user, "last_name", None)
    username = getattr(tg_user, "username", None)
    photo_url = getattr(tg_user, "photo_url", None)
    language_code_raw = getattr(tg_user, "language_code", None)
    language_code = _normalize_lang(language_code_raw)
    allows = getattr(tg_user, "allows_write_to_pm", getattr(u, "allows_write_to_pm", True))

    upd("first_name", first_name)
    upd("last_name", last_name)
    upd("username", username)
    upd("photo_url", photo_url)
    upd("language_code", language_code)
    upd("allows_write_to_pm", allows)

    # Обновляем display name
    new_name = get_display_name(first_name=first_name, last_name=last_name, username=username, telegram_id=u.telegram_id)
    if getattr(u, "name", None) != new_name:
        u.name = new_name
        changed = True

    return changed


def validate_and_sync_user(init_data: str, db: Session, *, create_if_missing: bool) -> User:
    """
    Валидирует initData, находит/создаёт пользователя и лениво обновляет его поля.
    """
    if not init_data:
        raise HTTPException(status_code=401, detail="initData is required")

    try:
        result = authenticator.validate(init_data)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Auth error: {str(e)}")

    tg_user = result.user
    telegram_id = tg_user.id

    user: Optional[User] = db.query(User).filter_by(telegram_id=telegram_id).first()

    if not user:
        if not create_if_missing:
            raise HTTPException(status_code=401, detail="User is not registered")
        # Создаём нового пользователя из Telegram-профиля
        user = User(
            telegram_id=telegram_id,
            first_name=getattr(tg_user, "first_name", None),
            last_name=getattr(tg_user, "last_name", None),
            username=getattr(tg_user, "username", None),
            photo_url=getattr(tg_user, "photo_url", None),
            language_code=_normalize_lang(getattr(tg_user, "language_code", None)),
            allows_write_to_pm=getattr(tg_user, "allows_write_to_pm", True),
        )
        user.name = get_display_name(
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            telegram_id=user.telegram_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    # Лениво обновляем поля существующего пользователя
    if _apply_user_fields_from_tg(user, tg_user):
        db.add(user)
        db.commit()
        db.refresh(user)

    return user


async def get_current_telegram_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Зависимость для защищённых ручек:
    - достаёт initData из запроса
    - валидирует
    - находит существующего пользователя
    - лениво обновляет его поля (включая language_code -> с фолбэком на 'en')
    """
    body = None
    if request.method in {"POST", "PUT", "PATCH"}:
        try:
            body = await request.json()
        except Exception:
            body = None

    init_data = _get_init_data_from_request(request, body)
    if not init_data:
        raise HTTPException(
            status_code=401,
            detail="initData required (JSON 'initData', header 'x-telegram-initdata' or '?init_data=...')",
        )

    return validate_and_sync_user(init_data, db, create_if_missing=False)


# --- ДОБАВЛЕНО: зависимость «создай, если нет» (нужна для акцепта группового инвайта) ---
async def get_current_telegram_user_or_create(request: Request, db: Session = Depends(get_db)) -> User:
    """
    То же самое, что get_current_telegram_user, но с create_if_missing=True.
    Использовать там, где новый пользователь заходит в приложение впервые по инвайт-ссылке.
    """
    body = None
    if request.method in {"POST", "PUT", "PATCH"}:
        try:
            body = await request.json()
        except Exception:
            body = None

    init_data = _get_init_data_from_request(request, body)
    if not init_data:
        raise HTTPException(
            status_code=401,
            detail="initData required (JSON 'initData', header 'x-telegram-initdata' or '?init_data=...')",
        )

    return validate_and_sync_user(init_data, db, create_if_missing=True)
