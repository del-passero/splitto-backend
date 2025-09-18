# src/routers/groups.py
# -----------------------------------------------------------------------------
# РОУТЕР: Группы
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import List, Optional, Dict
from datetime import datetime, date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from starlette import status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, select, cast
from sqlalchemy.sql.sqltypes import DateTime
from pydantic import BaseModel, constr

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
from src.utils.telegram_dep import get_current_telegram_user
from src.utils.groups import (
    require_membership,
    require_owner,
    ensure_group_active,
    has_group_debts,
)
from src.utils.balance import (
    calculate_group_balances_by_currency,
    greedy_settle_up_single_currency,
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
    # только активные membership'ы
    return [
        m.user_id
        for m in db.query(GroupMember.user_id)
        .filter(GroupMember.group_id == group_id, GroupMember.deleted_at.is_(None))
        .all()
    ]


def get_group_transactions(db: Session, group_id: int) -> List[Transaction]:
    return (
        db.query(Transaction)
        .filter(Transaction.group_id == group_id, Transaction.is_deleted == False)
        .options(joinedload(Transaction.shares))
        .all()
    )


def add_member_to_group(db: Session, group_id: int, user_id: int):
    """
    Идемпотентное добавление:
      - если уже активен — ничего не делаем;
      - если есть soft-deleted запись — реактивируем (deleted_at=NULL);
      - иначе — создаём новую запись.
    """
    exists = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == user_id
    ).first()
    if exists:
        if exists.deleted_at is not None:
            exists.deleted_at = None
            db.add(exists)
            db.commit()
            db.refresh(exists)
        return

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
    multicurrency: bool = Query(False, description="Вернуть балансы по каждой валюте отдельно"),
):
    require_membership(db, group_id, current_user.id)
    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)

    codes = sorted({(tx.currency_code or "").upper() for tx in transactions if tx.currency_code})
    decimals_map = {c.code: int(c.decimals) for c in db.query(Currency).filter(Currency.code.in_(codes)).all()}

    by_ccy = calculate_group_balances_by_currency(transactions, member_ids)

    if multicurrency:
        result: Dict[str, List[Dict[str, Decimal]]] = {}
        for code, balances in by_ccy.items():
            d = decimals_map.get(code, 2)
            result[code] = [{"user_id": uid, "balance": round(float(bal), d)} for uid, bal in balances.items()]
        return result

    group = get_group_or_404(db, group_id)
    code = (group.default_currency_code or "").upper()
    balances = by_ccy.get(code, {uid: Decimal("0") for uid in member_ids})
    d = decimals_map.get(code, 2)
    return [{"user_id": uid, "balance": round(float(bal), d)} for uid, bal in balances.items()]


@router.get("/{group_id}/settle-up")
def get_group_settle_up(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    multicurrency: bool = Query(False, description="Вернуть граф выплат по каждой валюте отдельно"),
):
    require_membership(db, group_id, current_user.id)
    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)

    codes = sorted({(tx.currency_code or "").upper() for tx in transactions if tx.currency_code})
    currencies = {c.code: int(c.decimals) for c in db.query(Currency).filter(Currency.code.in_(codes)).all()}
    by_ccy = calculate_group_balances_by_currency(transactions, member_ids)

    if multicurrency:
        result: Dict[str, List[Dict]] = {}
        for code, balances in by_ccy.items():
            d = currencies.get(code, 2)
            result[code] = greedy_settle_up_single_currency(balances, d, code)
        return result

    group = get_group_or_404(db, group_id)
    code = (group.default_currency_code or "").upper()
    balances = by_ccy.get(code, {uid: Decimal("0") for uid in member_ids})
    d = currencies.get(code, 2)
    return greedy_settle_up_single_currency(balances, d, code)

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

# ===== Группы пользователя (пагинация + поиск + X-Total-Count) =====

@router.get("/user/{user_id}")
def get_groups_for_user(
    user_id: int,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    members_preview_limit: int = Query(4, gt=0),
    include_hidden: bool = Query(False, description="Включать персонально скрытые группы"),
    include_archived: bool = Query(False, description="Включать архивные группы"),
    limit: int = Query(20, ge=1, le=200, description="Сколько групп вернуть"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации"),
    q: Optional[str] = Query(None, description="Поиск по названию/описанию"),
    # новое: сортировка
    sort_by: Optional[str] = Query(None, description="last_activity|name|created_at|members_count"),
    sort_dir: Optional[str] = Query(None, description="asc|desc"),
):
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    user_group_ids = [
        gid for (gid,) in db.query(GroupMember.group_id)
        .filter(GroupMember.user_id == user_id, GroupMember.deleted_at.is_(None))
        .all()
    ]
    if not user_group_ids:
        response.headers["X-Total-Count"] = "0"
        return []

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

    total = base_q.count()
    response.headers["X-Total-Count"] = str(int(total))

    # Подзапрос last_tx_date
    tx_dates_subq = (
        db.query(
            Transaction.group_id.label("g_id"),
            func.max(Transaction.date).label("last_tx_date"),
        )
        .filter(Transaction.is_deleted == False)
        .group_by(Transaction.group_id)
        .subquery()
    )

    # Сортировка
    sb = (sort_by or "").lower().strip()
    sd = (sort_dir or "").lower().strip()
    if sd not in ("asc", "desc"):
        sd = "desc"

    order_clauses = []
    if sb == "name":
        order_clauses = [getattr(Group.name, sd)()]
    elif sb == "created_at":
        order_clauses = [getattr(Group.id, sd)()]  # surrogate "created_at" по id
    elif sb == "members_count":
        # считаем количеством активных membership'ов
        members_count_subq = (
            db.query(
                GroupMember.group_id.label("mgid"),
                func.count(GroupMember.user_id).label("mcnt"),
            )
            .filter(GroupMember.deleted_at.is_(None))
            .group_by(GroupMember.group_id)
            .subquery()
        )
        base_q = base_q.outerjoin(members_count_subq, members_count_subq.c.mgid == Group.id)
        order_clauses = [getattr(members_count_subq.c.mcnt, sd)().nullslast(), getattr(Group.id, "desc")()]
    else:
        # default: last_activity (как и было)
        base_q = base_q.outerjoin(tx_dates_subq, tx_dates_subq.c.g_id == Group.id)
        order_clauses = [
            getattr(func.coalesce(tx_dates_subq.c.last_tx_date, cast(None, DateTime)), sd)().nullslast(),
            Group.archived_at.desc().nullslast(),
            Group.id.desc(),
        ]

    page_groups = (
        base_q
        .order_by(*order_clauses)
        .limit(limit)
        .offset(offset)
        .all()
    )
    if not page_groups:
        return []

    page_group_ids = {g.id for g in page_groups}

    # Словарь last_activity_at для выдачи (надёжно, без попыток "добавить поле" к ORM-объекту)
    last_dates = dict(
        db.query(Transaction.group_id, func.max(Transaction.date))
        .filter(Transaction.is_deleted == False, Transaction.group_id.in_(page_group_ids))
        .group_by(Transaction.group_id)
        .all()
    )

    members = (
        db.query(GroupMember, User)
        .join(User, GroupMember.user_id == User.id)
        .filter(
            GroupMember.group_id.in_(page_group_ids),
            GroupMember.deleted_at.is_(None),
        )
        .all()
    )
    from collections import defaultdict
    members_by_group = defaultdict(list)
    for gm, user in members:
        members_by_group[gm.group_id].append((gm, user))

    result = []
    for group in page_groups:
        gm_list = members_by_group.get(group.id, [])
        member_objs = [
            GroupMemberOut.from_orm(gm).dict() | {"user": UserOut.from_orm(user).dict()}
            for gm, user in gm_list
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
            "preview_members": preview_members,
            "status": group.status.value if hasattr(group.status, "value") else str(group.status),
            "archived_at": group.archived_at,
            "deleted_at": group.deleted_at,
            "default_currency_code": group.default_currency_code,
            "last_activity_at": last_dates.get(group.id),
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

    members_query = db.query(GroupMember).options(joinedload(GroupMember.user)).filter(
        GroupMember.group_id == group_id,
        GroupMember.deleted_at.is_(None),
    )
    members = members_query.offset(offset).limit(limit).all() if limit is not None else members_query.all()

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


@router.post("/{group_id}/unarchive")
def unarchive_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    return_full: bool = Query(False, description="Вернуть полную модель GroupOut"),
):
    group = require_owner(db, group_id, current_user.id)
    if group.status == GroupStatus.active:
        if return_full:
            return GroupOut.from_orm(group)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    group.status = GroupStatus.active
    group.archived_at = None
    db.commit()
    if return_full:
        db.refresh(group)
        return GroupOut.from_orm(group)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

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


@router.post("/{group_id}/restore")
def restore_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    to_active: bool = Query(False, description="Попытаться сразу активировать после восстановления"),
    return_full: bool = Query(False, description="Вернуть полную модель GroupOut вместо 204"),
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only owner can perform this action")
    if group.deleted_at is None:
        if return_full:
            return GroupOut.from_orm(group)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    group.deleted_at = None
    if to_active and not has_group_debts(db, group_id):
        group.status = GroupStatus.active
        group.archived_at = None
    else:
        group.status = GroupStatus.archived
        group.archived_at = datetime.utcnow()
    db.commit()
    if return_full:
        db.refresh(group)
        return GroupOut.from_orm(group)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# ===== Hard-delete (если нет транзакций) =====

@router.delete("/{group_id}/hard", status_code=status.HTTP_204_NO_CONTENT)
def hard_delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Жёсткое удаление:
      • только владелец,
      • только если группа уже soft-deleted,
      • только если в группе нет ТРАНЗАКЦИЙ (активных).
    """
    group = require_owner(db, group_id, current_user.id)
    if group.deleted_at is None:
        raise HTTPException(status_code=409, detail="Сначала выполните обычное удаление (soft-delete)")

    has_tx = db.query(Transaction.id).filter(
        Transaction.group_id == group_id,
        Transaction.is_deleted == False
    ).first() is not None
    if has_tx:
        raise HTTPException(status_code=409, detail="В группе есть транзакции — жёсткое удаление запрещено")

    # удаляем зависимые сущности
    db.query(GroupHidden).filter(GroupHidden.group_id == group_id).delete(synchronize_session=False)
    db.query(GroupInvite).filter(GroupInvite.group_id == group_id).delete(synchronize_session=False)
    db.query(GroupMember).filter(GroupMember.group_id == group_id).delete(synchronize_session=False)
    # удаляем саму группу
    db.query(Group).filter(Group.id == group_id).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# ===== Смена валюты группы =====

@router.patch("/{group_id}/currency", status_code=status.HTTP_204_NO_CONTENT)
def change_group_currency(
    group_id: int,
    code: str = Query(..., min_length=3, max_length=3),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    require_membership(db, group_id, current_user.id)
    group = get_group_or_404(db, group_id)
    ensure_group_active(group)

    norm_code = code.upper().strip()
    cur = db.scalar(select(Currency).where(Currency.code == norm_code, Currency.is_active.is_(True)))
    if not cur:
        raise HTTPException(status_code=404, detail="Currency not found or inactive")

    group.default_currency_code = norm_code
    db.commit()

# ===== Расписание (end_date / auto_archive) =====

class GroupScheduleUpdate(BaseModel):
    end_date: Optional[date] = None
    auto_archive: Optional[bool] = None

@router.patch("/{group_id}/schedule", response_model=GroupOut)
def update_group_schedule(
    group_id: int,
    payload: GroupScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    require_membership(db, group_id, current_user.id)
    group = get_group_or_404(db, group_id)
    ensure_group_active(group)

    fields_set = getattr(payload, "__fields_set__", getattr(payload, "model_fields_set", set()))

    if "end_date" in fields_set:
        if payload.end_date is None:
            group.end_date = None
            group.auto_archive = False
        else:
            today = date.today()
            if payload.end_date < today:
                raise HTTPException(status_code=422, detail="end_date must be today or later")
            group.end_date = payload.end_date

    if "auto_archive" in fields_set:
        if group.end_date is None:
            group.auto_archive = False
        else:
            group.auto_archive = bool(payload.auto_archive)

    db.commit()
    db.refresh(group)
    return group

class GroupUpdate(BaseModel):
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=120)] = None
    description: Optional[constr(strip_whitespace=True, max_length=500)] = None

@router.patch("/{group_id}", response_model=GroupOut)
def update_group_info(
    group_id: int,
    payload: GroupUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Частичное обновление названия/описания группы.
    Доступ: любой участник. Для активной группы.
    """
    require_membership(db, group_id, current_user.id)
    group = get_group_or_404(db, group_id)
    ensure_group_active(group)

    fields_set = getattr(payload, "__fields_set__", getattr(payload, "model_fields_set", set()))

    if "name" in fields_set and payload.name is not None:
        group.name = payload.name

    if "description" in fields_set:
        desc = payload.description
        group.description = (desc if desc is not None and desc != "" else None)

    db.commit()
    db.refresh(group)
    return group

# ===== Батч-превью долгов для карточек =====

def _round_amount(value: float, decimals: int) -> float:
    fmt = "{:0." + str(max(0, int(decimals))) + "f}"
    return float(fmt.format(value))

@router.get("/user/{user_id}/debts-preview")
def get_debts_preview(
    user_id: int,
    group_ids: str = Query(..., description="Список ID групп через запятую"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Возвращает по каждой группе суммарные долги для текущего пользователя:
      {
        "<group_id>": {
          "owe":  { "USD": 20.0, ... },   # я должен (по модулю)
          "owed": { "RUB": 150.0, ... }   # мне должны
        },
        ...
      }
    """
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        ids: List[int] = [int(x) for x in group_ids.split(",") if x.strip()]
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid group_ids")

    if not ids:
        return {}

    result: Dict[str, Dict[str, Dict[str, float]]] = {}
    for gid in ids:
        is_member = db.query(GroupMember.id).filter(
            GroupMember.group_id == gid,
            GroupMember.user_id == current_user.id,
            GroupMember.deleted_at.is_(None)
        ).first()
        if not is_member:
            continue

        members = get_group_member_ids(db, gid)
        txs = get_group_transactions(db, gid)
        if not txs:
            result[str(gid)] = {"owe": {}, "owed": {}}
            continue

        codes = sorted({(tx.currency_code or "").upper() for tx in txs if tx.currency_code})
        decimals_map = {c.code: int(c.decimals) for c in db.query(Currency).filter(Currency.code.in_(codes)).all()}
        by_ccy = calculate_group_balances_by_currency(txs, members)

        owe: Dict[str, float] = {}
        owed: Dict[str, float] = {}
        for code, balances in by_ccy.items():
            bal = float(balances.get(current_user.id, Decimal("0")))
            d = decimals_map.get(code, 2)
            if bal < 0:
                owe[code] = _round_amount(abs(bal), d)
            elif bal > 0:
                owed[code] = _round_amount(bal, d)
        result[str(gid)] = {"owe": owe, "owed": owed}

    return result
