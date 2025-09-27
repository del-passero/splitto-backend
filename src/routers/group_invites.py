# src/routers/group_invites.py
from __future__ import annotations

import re
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Body, Path, Request
from sqlalchemy.orm import Session

from src.db import get_db
from src.models.user import User
from src.models.group import Group

# Важно: берём прямую валидацию, чтобы уметь СОЗДАТЬ нового юзера (create_if_missing=True/False)
from src.utils.telegram_dep import validate_and_sync_user

from src.services.group_invite_token import (
    create_group_invite_token,
    parse_and_validate_token,
)
from src.services.group_membership import is_active_member, ensure_member

router = APIRouter(tags=["Инвайты групп"])


def _get_init_data(request: Request) -> Optional[str]:
    """Единая точка получения initData: заголовки, query, тело (на всякий случай)."""
    init_data = (
        request.headers.get("x-telegram-initdata")
        or request.headers.get("X-Telegram-InitData")
        or request.query_params.get("init_data")
    )
    return init_data


def _normalize_candidates(raw: str) -> List[str]:
    """
    Готовим набор «кандидатов» токена:
    - исходный
    - без префиксов join:/g: (если вдруг прилетело так)
    - base64url с добитым паддингом (если это оно)
    """
    t = (raw or "").strip()
    if not t:
        return []

    candidates = [t]

    for pref in ("join:", "JOIN:", "g:", "G:"):
        if t.startswith(pref):
            candidates.append(t[len(pref):])

    # base64url-паддинг — добавляем как дополнительный вариант
    if re.fullmatch(r"[A-Za-z0-9_-]+", t) and (len(t) % 4) != 0:
        padded = t + "=" * ((4 - (len(t) % 4)) % 4)
        candidates.append(padded)

    # уникализируем с сохранением порядка
    seen = set()
    uniq: List[str] = []
    for c in candidates:
        if c not in seen:
            uniq.append(c)
            seen.add(c)
    return uniq


@router.post("/groups/{group_id}/invite", response_model=dict)
def create_group_invite(
    group_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """
    Создать бессрочный инвайт-токен на вступление в группу.
    Требование: текущий пользователь — АКТИВНЫЙ участник группы.
    """
    # 1) initData обязательно, пользователя НЕ создаём
    init_data = _get_init_data(request)
    if not init_data:
        raise HTTPException(
            status_code=401,
            detail="initData required (header 'x-telegram-initdata' or '?init_data=...')",
        )

    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=False)

    # 2) Группа должна существовать
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    # 3) Требуем ИМЕННО активное членство
    if not is_active_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail={"code": "not_group_member"})

    # 4) Генерим токен
    token = create_group_invite_token(group_id=group_id, inviter_id=current_user.id)

    # Фронт соберёт t.me ссылку сам через startapp=<token>
    return {"token": token}


@router.post("/groups/invite/accept", response_model=dict)
async def accept_group_invite(
    token: str = Body(..., embed=True),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Принять инвайт в группу по токену.
    ► Здесь создаём пользователя при необходимости (create_if_missing=True).
    Возвращает { success, group_id }.
    """
    # 1) Подготовим пул кандидатов для разборщика токена
    candidates = _normalize_candidates(token)
    if not candidates:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    # 2) Валидируем токен
    parsed_group_id: Optional[int] = None
    for cand in candidates:
        try:
            group_id, _inviter_id = parse_and_validate_token(cand)
            parsed_group_id = group_id
            break
        except ValueError:
            continue

    if not parsed_group_id:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    # 3) Группа существует?
    group = db.query(Group).filter(Group.id == parsed_group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    # 4) Достаём initData (header / query / body)
    init_data = _get_init_data(request)
    if not init_data:
        try:
            body = await request.json()
        except Exception:
            body = {}
        init_data = body.get("initData") or body.get("init_data")

    if not init_data:
        raise HTTPException(
            status_code=401,
            detail="initData required (JSON 'initData', header 'x-telegram-initdata' or '?init_data=...')",
        )

    # 5) Валидируем + СОЗДАЁМ пользователя при необходимости
    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=True)
    # На всякий случай, если внутри была вставка:
    try:
        db.refresh(current_user)
    except Exception:
        pass

    # 6) Уже активный участник — ОК
    if is_active_member(db, parsed_group_id, current_user.id):
        return {"success": True, "group_id": parsed_group_id}

    # 7) Добавляем/реактивируем участника
    try:
        ensure_member(db, parsed_group_id, current_user.id)
    except ValueError as e:
        code = str(e) if str(e) else "cannot_join"
        raise HTTPException(status_code=400, detail={"code": code})

    return {"success": True, "group_id": parsed_group_id}
