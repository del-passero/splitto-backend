# src/routers/group_invites.py
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Body, Path, Request
from sqlalchemy.orm import Session

from src.db import get_db
from src.models.user import User
from src.models.group import Group
from src.utils.telegram_dep import validate_and_sync_user
from src.services.group_invite_token import (
    create_group_invite_token,
    parse_and_validate_token,
)
from src.services.group_membership import is_member, ensure_member

router = APIRouter(tags=["Инвайты групп"])
log = logging.getLogger("invites")


async def _extract_init_data(request: Request) -> str | None:
    """
    Достаёт Telegram initData из:
    - заголовков: x-telegram-init-data / x-telegram-initdata (в любых регистрах)
    - query: ?init_data=... / ?initData=...
    - JSON тела: {"init_data": "..."} / {"initData": "..."}
    """
    h = request.headers
    header_candidates = (
        "x-telegram-init-data",
        "x-telegram-initdata",
        "X-Telegram-Init-Data",
        "X-Telegram-InitData",
    )
    for k in header_candidates:
        v = h.get(k)
        if v:
            return v

    qp = request.query_params.get("init_data") or request.query_params.get("initData")
    if qp:
        return qp

    try:
        body = await request.json()
    except Exception:
        body = {}

    return body.get("init_data") or body.get("initData")


def _normalize_invite_token(raw: str | None) -> str | None:
    """
    Нормализуем токен:
    - режем префикс 'join:' (deep-link вида startapp=join:<token>)
    - убираем пробелы
    - для base64url добиваем '=' паддинг (Telegram часто режет)
    """
    if not raw:
        return raw
    raw = raw.strip().replace(" ", "")
    if raw.startswith("join:"):
        raw = raw.split(":", 1)[1]
    # добавляем паддинг только если это урл-безопасный base64 (символы [A-Za-z0-9_-])
    if all(c.isalnum() or c in "-_" for c in raw):
        pad = (-len(raw)) % 4
        if pad:
            raw += "=" * pad
    return raw


@router.post("/groups/{group_id}/invite", response_model=dict)
async def create_group_invite(
    group_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """
    Создать бессрочный инвайт-токен на вступление в группу.
    Требование: текущий пользователь — участник группы.
    Пользователя НЕ создаём (create_if_missing=False).
    """
    init_data = await _extract_init_data(request)
    if not init_data:
        raise HTTPException(status_code=401, detail={"code": "initdata_required"})

    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=False)

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail={"code": "not_group_member"})

    token = create_group_invite_token(group_id=group_id, inviter_id=current_user.id)
    return {"token": token}


@router.post("/groups/invite/accept", response_model=dict)
async def accept_group_invite(
    token: str | None = Body(None, embed=True),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Принять инвайт по токену. Разрешаем создавать нового юзера (create_if_missing=True).
    Возвращает: {"success": true, "group_id": <int>}
    """
    # 0) Токен может прийти откуда угодно — собираем все варианты
    try:
        body = await request.json()
    except Exception:
        body = {}

    token = (
        token
        or body.get("invite_token")
        or body.get("t")
        or request.query_params.get("token")
        or request.query_params.get("t")
        # на всякий — Telegram иногда пробрасывает так же, как пришло в URL
        or request.query_params.get("tgWebAppStartParam")
    )
    token = _normalize_invite_token(token)

    if not token:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    # 1) Валидируем токен
    try:
        group_id, _inviter_id = parse_and_validate_token(token)
    except HTTPException as e:
        raise e
    except ValueError:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    # 2) initData обязателен
    init_data = await _extract_init_data(request)
    if not init_data:
        raise HTTPException(status_code=401, detail={"code": "initdata_required"})

    # 3) Валидируем пользователя (с созданием при необходимости)
    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=True)

    # 4) Если уже в группе — успех
    if is_member(db, group_id, current_user.id):
        return {"success": True, "group_id": group_id}

    # 5) Добавляем в группу
    try:
        ensure_member(db, group_id, current_user.id)
    except ValueError as e:
        code = str(e) if str(e) else "cannot_join"
        raise HTTPException(status_code=400, detail={"code": code})

    return {"success": True, "group_id": group_id}
