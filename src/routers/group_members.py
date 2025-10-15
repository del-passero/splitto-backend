# src/routers/group_members.py
# РОУТЕР УЧАСТНИКОВ ГРУППЫ
# -----------------------------------------------------------------------------
# Soft-delete для членства, ре-активация, мультивалютные проверки нулевого баланса.

from typing import List, Optional, Union, Dict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from src.db import get_db
from src.models.friend import Friend
from src.models.group import Group, GroupStatus
from src.models.group_member import GroupMember
from src.models.transaction import Transaction
from src.models.transaction_share import TransactionShare
from src.models.user import User
from src.models.currency import Currency

from src.schemas.group_member import GroupMemberCreate, GroupMemberOut
from src.schemas.user import UserOut

from src.utils.telegram_dep import get_current_telegram_user
from src.utils.groups import (
    require_membership,
    require_owner,
    guard_mutation_for_member,
    ensure_group_active,
    get_group_member_ids,
    load_group_transactions,
)
from src.utils.balance import calculate_group_balances_by_currency

# === Логирование событий ===
from src.services.events import (
    log_event,
    MEMBER_ADDED,
    MEMBER_REMOVED,
    MEMBER_LEFT,
)

router = APIRouter()


def _err(code: str, message: str) -> Dict[str, str]:
    return {"code": code, "message": message}


def _pair_min_max(a: int, b: int) -> (int, int):
    return (a, b) if a < b else (b, a)


def add_mutual_friends_for_group(db: Session, group_id: int):
    """
    Bulk-добавление дружбы между ВСЕМИ активными участниками (deleted_at IS NULL)
    под каноническую модель дружбы: одна строка на пару (user_min, user_max).
    """
    member_ids = [
        m[0]
        for m in db.query(GroupMember.user_id)
        .filter(GroupMember.group_id == group_id, GroupMember.deleted_at.is_(None))
        .all()
    ]
    if not member_ids or len(member_ids) < 2:
        return

    # Уже существующие канонические пары
    existing_pairs = {
        (umin, umax)
        for (umin, umax) in db.query(Friend.user_min, Friend.user_max)
        .filter(
            Friend.user_min.in_(member_ids),
            Friend.user_max.in_(member_ids),
        )
        .all()
    }

    to_create: List[Friend] = []
    # Пройдемся по всем комбинациям (i < j), создадим недостающие пары
    for i in range(len(member_ids)):
        for j in range(i + 1, len(member_ids)):
            u1, u2 = member_ids[i], member_ids[j]
            umin, umax = _pair_min_max(u1, u2)
            if (umin, umax) not in existing_pairs:
                to_create.append(Friend(user_min=umin, user_max=umax, hidden_by_min=False, hidden_by_max=False))

    if to_create:
        db.bulk_save_objects(to_create)
        db.commit()


def _ensure_member_zero_balances_or_409(db: Session, group_id: int, user_id: int):
    """
    Проверка «по всем валютам отдельно»: у пользователя нет остатка ни в одной валюте.
    eps берём как половину минимального ден. шага валюты (10^-decimals / 2), по умолчанию decimals=2.
    """
    member_ids = get_group_member_ids(db, group_id)
    txs = load_group_transactions(db, group_id)

    by_ccy = calculate_group_balances_by_currency(txs, member_ids)  # {code: {uid: Decimal}}
    codes = sorted(by_ccy.keys())
    if not codes:
        return  # транзакций нет — можно выходить/удалять

    # загрузим decimals для присутствующих валют
    dec_map = {c.code: int(c.decimals) for c in db.query(Currency).filter(Currency.code.in_(codes)).all()}

    nonzero: Dict[str, float] = {}
    for code, balances in by_ccy.items():
        decimals = dec_map.get(code, 2)
        step = 10 ** (-decimals)
        eps = step / 2.0
        val = float(balances.get(user_id, 0) or 0)
        if abs(val) > eps:
            nonzero[code] = val

    if nonzero:
        raise HTTPException(
            status_code=409,
            detail=_err(
                "member_has_nonzero_balance",
                "У участника есть непогашенный баланс по валютам",
            ) | {"balances": nonzero},
        )


@router.post("/", response_model=GroupMemberOut)
def add_group_member(
    member: GroupMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Добавить участника:
      • Доступ — ЛЮБОЙ участник активной группы.
      • Реактивация: если запись существует и soft-deleted — выставляем deleted_at=NULL.
      • Ошибка 400, если уже активный участник.
    """
    group = guard_mutation_for_member(db, member.group_id, current_user.id)

    user_to_add = db.query(User).filter(User.id == member.user_id).first()
    if not user_to_add:
        raise HTTPException(status_code=404, detail=_err("user_not_found", "Пользователь не найден"))

    existing = db.query(GroupMember).filter(
        GroupMember.group_id == member.group_id,
        GroupMember.user_id == member.user_id,
    ).first()

    # Реактивация soft-deleted
    if existing and existing.deleted_at is not None:
        existing.deleted_at = None
        db.add(existing)

        # ЛОГ: участник добавлен (реактивация как админ-добавление)
        log_event(
            db,
            type=MEMBER_ADDED,
            actor_id=current_user.id,
            group_id=member.group_id,
            target_user_id=member.user_id,
            data={"member_id": member.user_id, "via": "admin_add", "reactivated": True},
        )

        db.commit()
        db.refresh(existing)
        add_mutual_friends_for_group(db, member.group_id)
        return existing

    # Уже активный — 400
    if existing and existing.deleted_at is None:
        raise HTTPException(status_code=400, detail=_err("already_member", "Пользователь уже в группе"))

    # Новая запись
    db_member = GroupMember(group_id=member.group_id, user_id=member.user_id)
    db.add(db_member)

    # ЛОГ: участник добавлен (через интерфейс участника — считаем как admin_add)
    log_event(
        db,
        type=MEMBER_ADDED,
        actor_id=current_user.id,
        group_id=member.group_id,
        target_user_id=member.user_id,
        data={"member_id": member.user_id, "via": "admin_add"},
    )

    db.commit()
    db.refresh(db_member)
    add_mutual_friends_for_group(db, member.group_id)
    return db_member


@router.get("/", response_model=Union[List[GroupMemberOut], dict])
def get_group_members(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, gt=0),
):
    """
    Тех-эндпойнт: возвращаем только **активные** membership'ы (deleted_at IS NULL).
    """
    query = db.query(GroupMember).options(joinedload(GroupMember.user)).filter(GroupMember.deleted_at.is_(None))
    total = query.count()
    if limit is not None:
        members = query.offset(offset).limit(limit).all()
    else:
        members = query.all()

    items = [GroupMemberOut.from_orm(m) for m in members]
    return {"total": total, "items": items} if limit is not None else items


@router.get("/group/{group_id}", response_model=Union[List[dict], dict])
def get_members_for_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, gt=0),
):
    """
    Состав группы виден только участникам. Отдаём только активные записи.
    """
    require_membership(db, group_id, current_user.id)

    query = (
        db.query(GroupMember, User)
        .join(User, GroupMember.user_id == User.id)
        .filter(GroupMember.group_id == group_id, GroupMember.deleted_at.is_(None))
    )

    total = query.count()
    rows = query.offset(offset).limit(limit).all() if limit is not None else query.all()

    items = [
        {
            "id": gm.id,
            "group_id": gm.group_id,
            "user": UserOut.from_orm(u).dict(),
        }
        for gm, u in rows
    ]

    return {"total": total, "items": items} if limit is not None else items


@router.delete("/{member_id}", status_code=204)
def delete_group_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Кик участника:
      • Только владелец активной группы.
      • Нельзя удалить владельца.
      • Разрешено ТОЛЬКО при нулевых остатках участника по всем валютам.
      • Реализация: soft-delete (deleted_at = now()).
    """
    member = db.query(GroupMember).filter(GroupMember.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail=_err("member_not_found", "Участник группы не найден"))

    group = db.query(Group).filter(Group.id == member.group_id, Group.deleted_at.is_(None)).first()
    if not group:
        raise HTTPException(status_code=404, detail=_err("group_not_found", "Группа не найдена"))

    require_owner(db, group.id, current_user.id)
    ensure_group_active(group)

    if member.user_id == group.owner_id:
        raise HTTPException(status_code=409, detail=_err("cannot_delete_owner", "Нельзя удалить владельца группы"))

    # мультивалютная проверка нулевого баланса
    _ensure_member_zero_balances_or_409(db, group.id, member.user_id)

    # soft-delete (и лог)
    if member.deleted_at is None:
        member.deleted_at = datetime.utcnow()
        db.add(member)

        log_event(
            db,
            type=MEMBER_REMOVED,
            actor_id=current_user.id,
            group_id=group.id,
            target_user_id=member.user_id,
            data={"member_id": member.user_id, "by_admin_id": current_user.id},
        )

        db.commit()
    return


@router.post("/group/{group_id}/leave", status_code=204)
def leave_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Самовыход участника:
      • Только участник активной группы.
      • Владелец не может выйти.
      • Разрешено ТОЛЬКО при нулевых остатках по всем валютам.
      • Реализация: soft-delete (deleted_at = now()).
    """
    member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user.id,
        GroupMember.deleted_at.is_(None),
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail=_err("forbidden_not_member", "Вы не являетесь участником группы"))

    group = db.query(Group).filter(Group.id == group_id, Group.deleted_at.is_(None)).first()
    if not group:
        raise HTTPException(status_code=404, detail=_err("group_not_found", "Группа не найдена"))

    if group.owner_id == current_user.id:
        raise HTTPException(status_code=409, detail=_err("owner_cannot_leave", "Владелец не может выйти из группы"))

    ensure_group_active(group)

    # мультивалютная проверка нулевого баланса
    _ensure_member_zero_balances_or_409(db, group.id, current_user.id)

    # soft-delete (и лог)
    if member.deleted_at is None:
        member.deleted_at = datetime.utcnow()
        db.add(member)

        log_event(
            db,
            type=MEMBER_LEFT,
            actor_id=current_user.id,
            group_id=group.id,
            target_user_id=current_user.id,
            data={"member_id": current_user.id},
        )

        db.commit()
    return
