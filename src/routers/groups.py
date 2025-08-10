# src/routers/groups.py
# РОУТЕР ДЛЯ ГРУПП: старый функционал + новые фичи и ПАГИНАЦИЯ
# -----------------------------------------------------------------------------
# Что здесь есть:
#   • Балансы и settle-up (как было) — добавлена проверка членства.
#   • Создание группы, список групп (теперь с limit/offset), детали группы (с offset/limit).
#   • Список групп пользователя (ПАГИНАЦИЯ + сортировка по "активности", X-Total-Count).
#   • Инвайты (создание/акцепт) — защищены, нельзя для archived/deleted.
#   • Персональное скрытие (hide/unhide) — per-user.
#   • Архивация/разархивация — глобально, только если нет долгов.
#   • Soft-delete/restore — только если нет долгов.
#   • Смена валюты группы (PATCH currency) — владелец, если в группе нет транзакций.
#
# Важно:
#   • Мы НЕ удаляем старое поведение, только усиливаем и добавляем опции.
#   • Новый порядок в /groups/user/{user_id}:
#       - фильтры (deleted/hidden/archived + q по name/description),
#       - считаем total из БАЗОВОГО запроса (без join'ов),
#       - сортируем по last_activity (max(tx.date) DESC NULLS LAST, затем archived_at DESC, затем id DESC),
#       - применяем limit/offset,
#       - собираем превью участников так же, как раньше.
#   • В ответ /groups/user/{user_id} добавлен заголовок `X-Total-Count` (тело НЕ меняем).

from __future__ import annotations

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from starlette import status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, select, cast
from sqlalchemy.sql.sqltypes import DateTime

from src.db import get_db
from src.models.group import Group, GroupStatus
from src.models.group_member import GroupMember
from src.models.group_invite import GroupInvite
from src.models.user import User
from src.models.transaction import Transaction
from src.models.group_hidden import GroupHidden
from src.models.currency import Currency
from src.schemas.group import GroupCreate, GroupOut
from src.schemas.group_invite import GroupInviteOut
from src.schemas.group_member import GroupMemberOut
from src.schemas.user import UserOut
from src.schemas.settlement import SettlementOut
from src.utils.balance import calculate_group_balances, greedy_settle_up
from src.utils.telegram_dep import get_current_telegram_user
from src.utils.groups import (
    require_membership,
    require_owner,
    ensure_group_active,
    has_group_debts,
)

import secrets

router = APIRouter()


# ===== Вспомогательные =====

def get_group_or_404(db: Session, group_id: int) -> Group:
    group = (
        db.query(Group)
        .filter(Group.id == group_id, Group.deleted_at.is_(None))
        .first()
    )
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    return group


def get_group_member_ids(db: Session, group_id: int) -> List[int]:
    return [
        m.user_id
        for m in db.query(GroupMember.user_id).filter(GroupMember.group_id == group_id).all()
    ]


def get_group_transactions(db: Session, group_id: int) -> List[Transaction]:
    return (
        db.query(Transaction)
        .filter(Transaction.group_id == group_id, Transaction.is_deleted == False)
        .options(joinedload(Transaction.shares))
        .all()
    )


def add_member_to_group(db: Session, group_id: int, user_id: int):
    exists = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == user_id
    ).first()
    if not exists:
        db_member = GroupMember(group_id=group_id, user_id=user_id)
        db.add(db_member)
        db.commit()
        db.refresh(db_member)


# ===== Балансы / Settle-up =====

@router.get("/{group_id}/balances")
def get_group_balances(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    require_membership(db, group_id, current_user.id)
    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)
    net_balance = calculate_group_balances(transactions, member_ids)
    return [
        {"user_id": uid, "balance": round(balance, 2)}
        for uid, balance in net_balance.items()
    ]


@router.get("/{group_id}/settle-up", response_model=List[SettlementOut])
def get_group_settle_up(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    require_membership(db, group_id, current_user.id)
    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)
    net_balance = calculate_group_balances(transactions, member_ids)
    settlements = greedy_settle_up(net_balance)
    return settlements


# ===== Создание и базовые списки =====

@router.post("/", response_model=GroupOut)
def create_group(group: GroupCreate, db: Session = Depends(get_db)):
    db_group = Group(name=group.name, description=group.description, owner_id=group.owner_id)
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    add_member_to_group(db, db_group.id, db_group.owner_id)
    return db_group


@router.get("/", response_model=List[GroupOut])
def get_groups(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return (
        db.query(Group)
        .filter(Group.deleted_at.is_(None))
        .order_by(Group.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


# ===== Группы пользователя (ПАГИНАЦИЯ + поиск + X-Total-Count) =====

@router.get("/user/{user_id}")
def get_groups_for_user(
    user_id: int,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    members_preview_limit: int = Query(4, gt=0),
    include_hidden: bool = Query(False, description="Включать персонально скрытые группы"),
    include_archived: bool = Query(False, description="Включать архивные группы"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None, description="Поиск по названию/описанию"),
):
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # 1) id групп пользователя
    user_group_ids = [
        gid for (gid,) in db.query(GroupMember.group_id).filter(GroupMember.user_id == user_id).all()
    ]
    if not user_group_ids:
        response.headers["X-Total-Count"] = "0"
        return []

    # 2) БАЗОВЫЙ ЗАПРОС С ФИЛЬТРАМИ (БЕЗ join'ов!) — ДЛЯ total
    base_q = db.query(Group).filter(
        Group.id.in_(user_group_ids),
        Group.deleted_at.is_(None),
    )
    if not include_archived:
        base_q = base_q.filter(Group.status == GroupStatus.active)

    if not include_hidden:
        base_q = base_q.outerjoin(
            GroupHidden,
            (GroupHidden.group_id == Group.id) & (GroupHidden.user_id == user_id)
        ).filter(GroupHidden.user_id.is_(None))

    if q:
        like = f"%{q.strip()}%"
        base_q = base_q.filter((Group.name.ilike(like)) | (Group.description.ilike(like)))

    # total считаем СЕЙЧАС — из base_q (без внешних join'ов и order_by)
    total = base_q.count()
    response.headers["X-Total-Count"] = str(int(total))

    # 3) ДОП. сортировка по "активности" + пагинация для items
    tx_dates_subq = (
        db.query(
            Transaction.group_id.label("g_id"),
            func.max(Transaction.date).label("last_tx_date"),
        )
        .filter(Transaction.is_deleted == False)
        .group_by(Transaction.group_id)
        .subquery()
    )

    page_q = (
        base_q.outerjoin(tx_dates_subq, tx_dates_subq.c.g_id == Group.id)
        .order_by(
            func.coalesce(tx_dates_subq.c.last_tx_date, cast(None, DateTime)).desc().nullslast(),
            Group.archived_at.desc().nullslast(),
            Group.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    page_groups = page_q.all()
    if not page_groups:
        return []

    page_group_ids = {g.id for g in page_groups}

    # 4) превью участников (как раньше)
    members = (
        db.query(GroupMember, User)
        .join(User, GroupMember.user_id == User.id)
        .filter(GroupMember.group_id.in_(page_group_ids))
        .all()
    )
    from collections import defaultdict
    members_by_group = defaultdict(list)
    for gm, user in members:
        members_by_group[gm.group_id].append((gm, user))

    result = []
    for group in page_groups:
        group_members = members_by_group.get(group.id, [])
        member_objs = [
            GroupMemberOut.from_orm(gm).dict() | {"user": UserOut.from_orm(user).dict()}
            for gm, user in group_members
        ]
        member_objs_sorted = sorted(
            member_objs,
            key=lambda m: (m["user"]["id"] != group.owner_id, m["user"]["id"])
        )
        preview_members = member_objs_sorted[:members_preview_limit]
        members_count = len({m["user"]["id"] for m in member_objs})

        result.append({
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "owner_id": group.owner_id,
            "members_count": members_count,
            "preview_members": preview_members
        })

    return result


# ===== Детали группы =====

@router.get("/{group_id}/detail/", response_model=GroupOut)
def group_detail(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, gt=0)
):
    group = get_group_or_404(db, group_id)
    require_membership(db, group_id, current_user.id)

    members_query = db.query(GroupMember).options(joinedload(GroupMember.user))
    if limit is not None:
        members = (
            members_query.filter(GroupMember.group_id == group_id)
            .offset(offset)
            .limit(limit)
            .all()
        )
    else:
        members = members_query.filter(GroupMember.group_id == group_id).all()

    group.members = members
    return group


# ===== Инвайты =====

@router.post("/{group_id}/invite", response_model=GroupInviteOut)
def create_group_invite(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    group = require_membership(db, group_id, current_user.id)
    ensure_group_active(group)

    invite = db.query(GroupInvite).filter(GroupInvite.group_id == group_id).first()
    if not invite:
        token = secrets.token_urlsafe(16)
        invite = GroupInvite(group_id=group_id, token=token)
        db.add(invite)
        db.commit()
        db.refresh(invite)
    return invite


@router.post("/accept-invite")
def accept_group_invite(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user)
):
    invite = db.query(GroupInvite).filter(GroupInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Инвайт не найден")

    group = get_group_or_404(db, invite.group_id)
    if group.status == GroupStatus.archived:
        raise HTTPException(status_code=409, detail="Группа архивирована")

    add_member_to_group(db, group.id, current_user.id)
    return {"detail": "Успешно добавлен в группу"}


# ===== Персональное скрытие =====

@router.post("/{group_id}/hide", status_code=status.HTTP_204_NO_CONTENT)
def hide_group_for_me(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    require_membership(db, group_id, current_user.id)

    exists = db.scalar(
        select(func.count()).select_from(GroupHidden).where(
            GroupHidden.group_id == group_id,
            GroupHidden.user_id == current_user.id,
        )
    )
    if exists:
        return

    db.add(GroupHidden(group_id=group_id, user_id=current_user.id))
    db.commit()


@router.post("/{group_id}/unhide", status_code=status.HTTP_204_NO_CONTENT)
def unhide_group_for_me(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    require_membership(db, group_id, current_user.id)

    row = db.query(GroupHidden).filter(
        GroupHidden.group_id == group_id,
        GroupHidden.user_id == current_user.id,
    ).first()
    if not row:
        return
    db.delete(row)
    db.commit()


# ===== Архивация (глобально) =====

@router.post("/{group_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    group = require_owner(db, group_id, current_user.id)
    if group.status == GroupStatus.archived:
        return
    if has_group_debts(db, group_id):
        raise HTTPException(status_code=409, detail="В группе есть непогашенные долги")

    group.status = GroupStatus.archived
    group.archived_at = datetime.utcnow()
    db.commit()


@router.post("/{group_id}/unarchive", status_code=status.HTTP_204_NO_CONTENT)
def unarchive_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    group = require_owner(db, group_id, current_user.id)
    if group.status == GroupStatus.active:
        return
    group.status = GroupStatus.active
    group.archived_at = None
    db.commit()


# ===== Soft-delete / Restore =====

@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    group = require_owner(db, group_id, current_user.id)
    if group.deleted_at is not None:
        return
    if has_group_debts(db, group_id):
        raise HTTPException(status_code=409, detail="В группе есть непогашенные долги")

    group.deleted_at = datetime.utcnow()
    db.commit()


@router.post("/{group_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only owner can perform this action")
    if group.deleted_at is None:
        return

    group.deleted_at = None
    group.status = GroupStatus.archived
    group.archived_at = datetime.utcnow()
    db.commit()


# ===== Смена валюты группы =====

@router.patch("/{group_id}/currency", status_code=status.HTTP_204_NO_CONTENT)
def change_group_currency(
    group_id: int,
    code: str = Query(..., min_length=3, max_length=3),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    group = require_owner(db, group_id, current_user.id)
    ensure_group_active(group)

    norm_code = code.upper().strip()

    cur = db.scalar(select(Currency).where(Currency.code == norm_code, Currency.is_active.is_(True)))
    if not cur:
        raise HTTPException(status_code=404, detail="Currency not found or inactive")

    exists_tx = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.group_id == group_id, Transaction.is_deleted.is_(False))
    )
    if exists_tx:
        raise HTTPException(status_code=409, detail="Currency cannot be changed after transactions exist")

    group.default_currency_code = norm_code
    db.commit()
