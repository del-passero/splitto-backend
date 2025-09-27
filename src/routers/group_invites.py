# src/routers/group_invites.py
from __future__ import annotations

import os
import re
from typing import Optional, List
from urllib.parse import quote

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
from src.services.group_membership import is_active_member, ensure_member

router = APIRouter(tags=["Инвайты групп"])

BOT_USERNAME = (
    os.environ.get("TELEGRAM_BOT_USERNAME")
    or os.environ.get("BOT_USERNAME")
    or os.environ.get("TELEGRAM_BOT_NAME")
    or ""
).strip()


def _get_init_data(request: Request) -> Optional[str]:
    return (
        request.headers.get("x-telegram-initdata")
        or request.headers.get("X-Telegram-InitData")
        or request.query_params.get("init_data")
    )


def _normalize_candidates(raw: str) -> List[str]:
    t = (raw or "").strip()
    if not t:
        return []
    candidates = [t]
    for pref in ("join:", "JOIN:", "g:", "G:"):
        if t.startswith(pref):
            candidates.append(t[len(pref):])
    if re.fullmatch(r"[A-Za-z0-9_-]+", t) and (len(t) % 4) != 0:
        candidates.append(t + "=" * ((4 - (len(t) % 4)) % 4))
    seen, uniq = set(), []
    for c in candidates:
        if c not in seen:
            uniq.append(c); seen.add(c)
    return uniq


def _build_deep_link(token: str) -> Optional[str]:
    """Ссылка, которая сразу откроет WebApp с нужным start_param."""
    if not BOT_USERNAME:
        return None
    return f"https://t.me/{BOT_USERNAME}?startapp={quote(token)}"


@router.post("/groups/{group_id}/invite", response_model=dict)
def create_group_invite(
    group_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """
    Создать бессрочный инвайт-токен на вступление в группу.
    Требование: текущий пользователь — АКТИВНЫЙ участник группы.
    Возвращаем также deep_link.
    """
    init_data = _get_init_data(request)
    if not init_data:
        raise HTTPException(status_code=401, detail="initData required")

    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=False)

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    if not is_active_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail={"code": "not_group_member"})

    token = create_group_invite_token(group_id=group_id, inviter_id=current_user.id)
    deep_link = _build_deep_link(token)
    return {"token": token, "deep_link": deep_link}


@router.post("/groups/invite/accept", response_model=dict)
async def accept_group_invite(
    token: str = Body(..., embed=True),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Принять инвайт: создаём пользователя при необходимости, затем добавляем/реактивируем в группе.
    Возвращаем { success, group_id }.
    """
    candidates = _normalize_candidates(token)
    if not candidates:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

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

    group = db.query(Group).filter(Group.id == parsed_group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    init_data = _get_init_data(request)
    if not init_data:
        try:
            body = await request.json()
        except Exception:
            body = {}
        init_data = body.get("initData") or body.get("init_data")
    if not init_data:
        raise HTTPException(status_code=401, detail="initData required")

    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=True)

    if is_active_member(db, parsed_group_id, current_user.id):
        return {"success": True, "group_id": parsed_group_id}

    try:
        ensure_member(db, parsed_group_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": str(e) or "cannot_join"})

    return {"success": True, "group_id": parsed_group_id}
