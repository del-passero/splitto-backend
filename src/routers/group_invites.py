# src/routers/group_invites.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Body, Path, Request
from sqlalchemy.orm import Session

from src.db import get_db
from src.models.user import User
from src.models.group import Group

# Важно: берём прямую валидацию, чтобы уметь СОЗДАТЬ нового юзера (create_if_missing=True)
from src.utils.telegram_dep import validate_and_sync_user

from src.services.group_invite_token import (
    create_group_invite_token,
    parse_and_validate_token,
)
from src.services.group_membership import is_member, ensure_member

router = APIRouter(tags=["Инвайты групп"])


@router.post("/groups/{group_id}/invite", response_model=dict)
def create_group_invite(
    group_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    request: Request = None,  # оставлено на будущее, если понадобится трекать initData
):
    """
    Создать бессрочный инвайт-токен на вступление в группу.
    Требование: текущий пользователь — участник группы.
    Проверку членства делаем через validate_and_sync_user(create_if_missing=False),
    чтобы не плодить лишние зависимости на get_current_telegram_user.
    """
    # Нам здесь нужен текущий пользователь, НО не создавать нового.
    init_data = (
        request.headers.get("x-telegram-initdata")
        or request.headers.get("X-Telegram-InitData")
        or request.query_params.get("init_data")
    )
    if init_data is None:
        # попробуем из тела (initData)
        try:
            body_json = request.json and request._body  # type: ignore[attr-defined]
        except Exception:
            body_json = None
        if not body_json:
            try:
                body_json = {}
            except Exception:
                body_json = {}
    # безопасно дочитаем body как json (синхронный путь FastAPI тут не обязателен)
    try:
        # FastAPI сам распарсит, если это был JSON
        pass
    except Exception:
        pass

    # Сознательно просим НЕ создавать пользователя: только валидировать и найти
    try:
        current_user: User = validate_and_sync_user(init_data, db, create_if_missing=False)  # type: ignore[arg-type]
    except HTTPException as e:
        # Если нет initData или невалидно — запретим создавать инвайт
        raise e

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail={"code": "not_group_member"})

    token = create_group_invite_token(group_id=group_id, inviter_id=current_user.id)
    # Бек не строит полную ссылку — фронт подставит startapp=<token>.
    return {"token": token}


@router.post("/groups/invite/accept", response_model=dict)
async def accept_group_invite(
    token: str = Body(..., embed=True),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Принять инвайт в группу по токену.
    ► Ключевой момент: здесь мы допускаем НОВОГО пользователя и создаём его,
      если он пришёл по ссылке впервые (create_if_missing=True).
    Возвращает { success, group_id }.
    """
    # 1) Разобрать и проверить токен
    try:
        group_id, _inviter_id = parse_and_validate_token(token)
    except ValueError:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    # 2) Достать initData из запроса (заголовок / query / тело)
    init_data = (
        request.headers.get("x-telegram-initdata")
        or request.headers.get("X-Telegram-InitData")
        or request.query_params.get("init_data")
    )
    if not init_data:
        try:
            body = await request.json()
        except Exception:
            body = {}
        # Поддержим оба ключа — и initData, и init_data
        init_data = body.get("initData") or body.get("init_data")

    if not init_data:
        raise HTTPException(
            status_code=401,
            detail="initData required (JSON 'initData', header 'x-telegram-initdata' or '?init_data=...')",
        )

    # 3) Валидируем + СОЗДАЁМ пользователя при необходимости
    current_user: User = validate_and_sync_user(init_data, db, create_if_missing=True)

    # 4) Уже в группе — ОК
    if is_member(db, group_id, current_user.id):
        return {"success": True, "group_id": group_id}

    # 5) Добавляем в группу (идемпотентно)
    try:
        ensure_member(db, group_id, current_user.id)
    except ValueError as e:
        code = str(e) if str(e) else "cannot_join"
        raise HTTPException(status_code=400, detail={"code": code})

    return {"success": True, "group_id": group_id}
