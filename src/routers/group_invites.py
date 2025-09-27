# src/routers/group_invites.py
from __future__ import annotations

import os
import re
import logging
from typing import Optional, List, Tuple
from urllib.parse import parse_qsl, unquote, quote

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

# используем готовую утилиту автодобавления друзей из routers/group_members
from src.routers.group_members import add_mutual_friends_for_group

router = APIRouter(tags=["Инвайты групп"])
BOT_USERNAME = (os.environ.get("TELEGRAM_BOT_USERNAME") or "").strip()
LOG = logging.getLogger("group_invites")


def _get_init_data(request: Request) -> Optional[str]:
    return (
        request.headers.get("x-telegram-initdata")
        or request.headers.get("X-Telegram-InitData")
        or request.query_params.get("init_data")
    )


def _extract_start_param_from_initdata(init_data: str) -> Optional[str]:
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
    except Exception:
        return None
    for k, v in pairs:
        if k in ("start_param", "start", "startapp", "tgWebAppStartParam"):
            v = unquote(v or "").strip()
            return v or None
    return None


def _normalize_token(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    t = raw.strip()
    lo = t.lower()
    if lo.startswith("join:"):
        t = t[5:]
    elif lo.startswith("g:"):
        t = t[2:]
    if t.startswith("token="):
        t = t[6:]
    return t or None


def _normalize_candidates(raw: str) -> List[str]:
    t = (raw or "").strip()
    if not t:
        return []
    cands = [t]
    for pref in ("join:", "JOIN:", "g:", "G:"):
        if t.startswith(pref):
            cands.append(t[len(pref):])
    if re.fullmatch(r"[A-Za-z0-9_-]+", t) and (len(t) % 4) != 0:
        cands.append(t + "=" * ((4 - (len(t) % 4)) % 4))
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


def _extract_token_fallbacks(
    request: Request, init_data: Optional[str], body_token: Optional[str],
) -> Tuple[str, List[str], str]:
    if body_token:
        tok = _normalize_token(body_token)
        return tok or "", _normalize_candidates(tok or ""), "body"
    if init_data:
        sp = _normalize_token(_extract_start_param_from_initdata(init_data))
        if sp:
            return sp, _normalize_candidates(sp), "initData"
    for key in ("startapp", "tgWebAppStartParam", "start"):
        qv = _normalize_token(request.query_params.get(key))
        if qv:
            return qv, _normalize_candidates(qv), "query"
    return "", [], "none"


def _build_deep_link(token: str) -> Optional[str]:
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
    Создать бессрочный групповой инвайт-токен (GINV_...).
    Требование: текущий пользователь — активный участник группы.
    """
    init_data = _get_init_data(request)
    if not init_data:
        raise HTTPException(status_code=401, detail="initData required")

    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=False)

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail={"code": "not_group_member"})

    token = create_group_invite_token(group_id=group_id, inviter_id=current_user.id)

    # защита от путаницы с «дружеским» токеном
    if not token.startswith("GINV_"):
        LOG.error("create_group_invite: wrong token format returned")
        raise HTTPException(status_code=500, detail={"code": "server_wrong_token_format"})

    deep_link = _build_deep_link(token)
    return {"token": token, "deep_link": deep_link}


@router.post("/groups/invite/preview", response_model=dict)
async def preview_group_invite(
    token: Optional[str] = Body(None, embed=True),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Превью приглашения: возвращает { group, inviter, already_member }.
    Пользователя создаём при необходимости (create_if_missing=True).
    """
    # 1) initData
    init_data = _get_init_data(request)
    if not init_data:
        try:
            body = await request.json()
        except Exception:
            body = {}
        init_data = body.get("initData") or body.get("init_data")

    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=True)

    # 2) токен из body/initData/query
    canonical, candidates, _ = _extract_token_fallbacks(request, init_data, token)
    if not candidates:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    parsed_group_id: Optional[int] = None
    inviter_id: Optional[int] = None
    parse_err: Optional[str] = None

    for cand in candidates:
        try:
            gid, inv = parse_and_validate_token(cand)
            parsed_group_id, inviter_id = gid, inv
            parse_err = None
            break
        except ValueError as e:
            parse_err = str(e) or "bad_token"
            continue

    if not parsed_group_id:
        raise HTTPException(status_code=400, detail={"code": parse_err or "bad_token"})

    # 3) сущности
    group = db.query(Group).filter(Group.id == parsed_group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    inviter = db.query(User).filter(User.id == inviter_id).first() if inviter_id else None
    already = is_member(db, parsed_group_id, current_user.id)

    def _get(obj, field, default=None):
        return getattr(obj, field) if hasattr(obj, field) else default

    return {
        "group": {"id": group.id, "name": _get(group, "name"), "avatar_url": _get(group, "avatar_url")},
        "inviter": inviter
        and {
            "id": inviter.id,
            "name": _get(inviter, "name"),
            "username": _get(inviter, "username"),
            "photo_url": _get(inviter, "photo_url"),
        },
        "already_member": already,
    }


@router.post("/groups/invite/accept", response_model=dict)
async def accept_group_invite(
    token: Optional[str] = Body(None, embed=True),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Принять инвайт: создаём пользователя при необходимости, активируем/создаём membership
    и после успешного вступления добавляем взаимную дружбу между всеми активными участниками.
    Возвращает { success: true, group_id }.
    """
    # 1) initData
    init_data = _get_init_data(request)
    if not init_data:
        try:
            body = await request.json()
        except Exception:
            body = {}
        init_data = body.get("initData") or body.get("init_data")

    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=True)

    # 2) токен из body/initData/query
    _, candidates, _ = _extract_token_fallbacks(request, init_data, token)
    if not candidates:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    parsed_group_id: Optional[int] = None
    parse_err: Optional[str] = None

    for cand in candidates:
        try:
            gid, _ = parse_and_validate_token(cand)
            parsed_group_id = gid
            parse_err = None
            break
        except ValueError as e:
            parse_err = str(e) or "bad_token"
            continue

    if not parsed_group_id:
        raise HTTPException(status_code=400, detail={"code": parse_err or "bad_token"})

    # 3) существование группы
    group = db.query(Group).filter(Group.id == parsed_group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    # 4) уже активный участник
    if is_member(db, parsed_group_id, current_user.id):
        return {"success": True, "group_id": parsed_group_id}

    # 5) вступаем (создаём/реактивируем)
    ensure_member(db, parsed_group_id, current_user.id)

    # 6) автодружба между всеми активными участниками группы
    try:
        add_mutual_friends_for_group(db, parsed_group_id)
    except Exception as e:
        # не блокируем вступление из-за дружбы; логируем
        LOG.warning("add_mutual_friends_for_group failed: %s", e)

    return {"success": True, "group_id": parsed_group_id}
