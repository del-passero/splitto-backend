# src/routers/group_invites.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Body, Path
from sqlalchemy.orm import Session

from src.db import get_db
from src.models.user import User
from src.models.group import Group
from src.utils.telegram_dep import get_current_telegram_user

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
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Создать бессрочный инвайт-токен на вступление в группу.
    Требование: текущий пользователь — участник группы.
    """
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail={"code": "not_group_member"})

    token = create_group_invite_token(group_id=group_id, inviter_id=current_user.id)
    # Бек не строит полную ссылку — фронт подставит startapp=<token> как в дружбе.
    return {"token": token}

@router.post("/groups/invite/accept", response_model=dict)
def accept_group_invite(
    token: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Принять инвайт в группу по токену. Если уже участник — просто success.
    Возвращает { success, group_id }.
    """
    try:
        group_id, _inviter_id = parse_and_validate_token(token)
    except ValueError:
        raise HTTPException(status_code=400, detail={"code": "bad_token"})

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail={"code": "group_not_found"})

    # Уже в группе — ок
    if is_member(db, group_id, current_user.id):
        return {"success": True, "group_id": group_id}

    try:
        ensure_member(db, group_id, current_user.id)
    except ValueError as e:
        code = str(e) if str(e) else "cannot_join"
        raise HTTPException(status_code=400, detail={"code": code})

    return {"success": True, "group_id": group_id}
