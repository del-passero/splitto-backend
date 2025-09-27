# src/routers/group_invites.py
from __future__ import annotations

import os
import re
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
from src.services.group_membership import is_member, is_active_member, ensure_member

router = APIRouter(tags=["Инвайты групп"])

BOT_USERNAME = (os.environ.get("TELEGRAM_BOT_USERNAME") or "").strip()


# ---------------- helpers ----------------

def _get_init_data(request: Request) -> Optional[str]:
    return (
        request.headers.get("x-telegram-initdata")
        or request.headers.get("X-Telegram-InitData")
        or request.query_params.get("init_data")
    )


def _extract_start_param_from_initdata(init_data: str) -> Optional[str]:
    """initData — подписанная query-строка Telegram; ищём start_param/start/startapp/tgWebAppStartParam."""
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
    """Как есть, без join:/g:, и вариант с base64url-паддингом."""
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
            out.append(c); seen.add(c)
    return out


def _extract_token_fallbacks(
    request: Request,
    init_data: Optional[str],
    body_token: Optional[str],
) -> Tuple[Optional[str], List[str]]:
    """
    Возвращает (canonical_token, candidates):
      1) token из body (если есть),
      2) иначе из initData.start_param,
      3) иначе из query (?startapp|?tgWebAppStartParam|?start)
    """
    # 1) body
    if body_token:
        tok = _normalize_token(body_token)
        return tok, _normalize_candidates(tok or "")

    # 2) initData.start_param
    if init_data:
        sp = _extract_start_param_from_initdata(init_data)
        sp = _normalize_token(sp)
        if sp:
            return sp, _normalize_candidates(sp)

    # 3) query fallbacks (на случай, если клиент заходит по web-link)
    for key in ("startapp", "tgWebAppStartParam", "start"):
        qv = request.query_params.get(key)
        qv = _normalize_token(qv)
        if qv:
            return qv, _normalize_candidates(qv)

    return None, []


def _build_deep_link(token: str) -> Optional[str]:
    if not BOT_USERNAME:
        return None
    return f"https://t.me/{BOT_USERNAME}?startapp={quote(token)}"


# ---------------- endpoints ----------------

@router.post("/groups/{group_id}/invite", response_model=dict)
def create_group_invite(
    group_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """
    Создать бессрочный инвайт-токен на вступление в группу.
    Требование: текущий пользователь — активный участник группы.
    Возвращает { token, deep_link }.
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


@router.post("/groups/invite/preview", response_model=dict)
async def preview_group_invite(
    token: Optional[str] = Body(None, embed=True),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Данные для модалки: кто пригласил, что за группа, уже ли участник.
    Источники токена: body → initData.start_param → query (?startapp|?tgWebAppStartParam|?start)
    """
    # initData нужен для auth + (в Telegram) содержит start_param
    init_data = _get_init_data(request)
    if not init_data:
        try:
            body = await request.json()
        except Exception:
            body = {}
        init_data = body.get("initData") or body.get("init_data")

    # validate auth (если нет initData — это веб-ссылка извне TG: user всё равно должен быть уже создан)
    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=True)

    # извлечём токен из всех возможных источников
    canonical, candidates = _extract_token_fallbacks(request, init_data, token)
    if not candidates:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    parsed_group_id: Optional[int] = None
    inviter_id: Optional[int] = None
    for cand in candidates:
        try:
            gid, inv = parse_and_validate_token(cand)
            parsed_group_id, inviter_id = gid, inv
            break
        except ValueError:
            continue
    if not parsed_group_id:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    group = db.query(Group).filter(Group.id == parsed_group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    inviter = db.query(User).filter(User.id == inviter_id).first() if inviter_id else None

    def _get(obj, field, default=None):
        return getattr(obj, field) if hasattr(obj, field) else default

    already = is_active_member(db, parsed_group_id, current_user.id)

    return {
        "group": {
            "id": group.id,
            "name": _get(group, "name", None),
            "avatar_url": _get(group, "avatar_url", None),
        },
        "inviter": inviter
        and {
            "id": inviter.id,
            "name": _get(inviter, "name", None),
            "username": _get(inviter, "username", None),
            "photo_url": _get(inviter, "photo_url", None),
        },
        "already_member": already,
        "token_source": ("body" if token else ("initData" if canonical and init_data else "query")),
    }


@router.post("/groups/invite/accept", response_model=dict)
async def accept_group_invite(
    token: Optional[str] = Body(None, embed=True),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Вступить в группу по инвайту (нажатие «Вступить в группу»).
    Источники токена: body → initData.start_param → query (?startapp|?tgWebAppStartParam|?start)
    """
    init_data = _get_init_data(request)
    if not init_data:
        try:
            body = await request.json()
        except Exception:
            body = {}
        init_data = body.get("initData") or body.get("init_data")

    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=True)

    canonical, candidates = _extract_token_fallbacks(request, init_data, token)
    if not candidates:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    parsed_group_id: Optional[int] = None
    for cand in candidates:
        try:
            gid, _ = parse_and_validate_token(cand)
            parsed_group_id = gid
            break
        except ValueError:
            continue
    if not parsed_group_id:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    group = db.query(Group).filter(Group.id == parsed_group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    if is_member(db, parsed_group_id, current_user.id):
        return {"success": True, "group_id": parsed_group_id}

    try:
        ensure_member(db, parsed_group_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": str(e) or "cannot_join"})

    return {"success": True, "group_id": parsed_group_id}
