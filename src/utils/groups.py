# src/utils/groups.py
# ОБЩИЕ ХЕЛПЕРЫ ДЛЯ РАБОТЫ С ГРУППАМИ.

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional, Set, List, Dict, Tuple

from fastapi import HTTPException
from starlette import status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session, joinedload

from ..models.group import Group, GroupStatus
from ..models.group_member import GroupMember
from ..models.group_category import GroupCategory
from ..models.transaction import Transaction

# =========================
# БАЗОВЫЕ ГАРДЫ / ЗАГРУЗКИ
# =========================

def get_group_or_404(db: Session, group_id: int, *, include_deleted: bool = False) -> Group:
    stmt = select(Group).where(Group.id == group_id)
    if not include_deleted:
        stmt = stmt.where(Group.deleted_at.is_(None))
    group = db.scalar(stmt)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


def require_membership(db: Session, group_id: int, user_id: int) -> Group:
    """
    Проверяет активное членство (deleted_at IS NULL).
    """
    group = get_group_or_404(db, group_id)
    is_member = db.scalar(
        select(func.count())
        .select_from(GroupMember)
        .where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
            GroupMember.deleted_at.is_(None),
        )
    )
    if not is_member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a group member")
    return group


def require_owner(db: Session, group_id: int, user_id: int) -> Group:
    group = get_group_or_404(db, group_id)
    if group.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner can perform this action")
    return group


def ensure_group_not_deleted(group: Group) -> None:
    if group.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group is deleted")


def ensure_group_not_archived(group: Group) -> None:
    if group.status == GroupStatus.archived:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group is archived")


def ensure_group_active(group: Group) -> None:
    ensure_group_not_deleted(group)
    ensure_group_not_archived(group)


def guard_mutation_for_member(db: Session, group_id: int, user_id: int) -> Group:
    group = require_membership(db, group_id, user_id)
    ensure_group_active(group)
    return group


def guard_mutation_for_owner(db: Session, group_id: int, user_id: int) -> Group:
    group = require_owner(db, group_id, user_id)
    ensure_group_active(group)
    return group


# =========================
# ЧЛЕНЫ ГРУППЫ / КАТЕГОРИИ
# =========================

def get_group_member_ids(db: Session, group_id: int) -> List[int]:
    """
    Возвращает только активные membership'ы.
    """
    rows = db.execute(
        select(GroupMember.user_id).where(
            GroupMember.group_id == group_id,
            GroupMember.deleted_at.is_(None),
        )
    ).all()
    return [uid for (uid,) in rows]


def get_allowed_category_ids(db: Session, group_id: int) -> Optional[Set[int]]:
    rows = db.execute(
        select(GroupCategory.category_id).where(GroupCategory.group_id == group_id)
    ).all()
    if not rows:
        return None
    return {cid for (cid,) in rows}


def is_category_allowed(allowed_ids: Optional[Set[int]], category_id: Optional[int]) -> bool:
    if category_id is None:
        return True
    if allowed_ids is None:
        return True
    return category_id in allowed_ids


# =========================
# ТРАНЗАКЦИИ
# =========================

def load_group_transactions(db: Session, group_id: int) -> List[Transaction]:
    """
    Загружает активные транзакции группы с подгруженными долями.
    Для joinedload коллекций используем .unique() перед .scalars()
    (SQLAlchemy 2.x) чтобы убрать дубли.
    Учитываем исторические записи с is_deleted = NULL как «не удалённые».
    """
    stmt = (
        select(Transaction)
        .where(
            Transaction.group_id == group_id,
            or_(Transaction.is_deleted.is_(False), Transaction.is_deleted.is_(None)),
        )
        .options(joinedload(Transaction.shares))
        .order_by(Transaction.date.asc(), Transaction.id.asc())
    )
    return db.execute(stmt).unique().scalars().all()


# =========================
# ПРОВЕРКИ ДОЛГОВ / БАЛАНСОВ
# =========================

def _D(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _nets_by_currency_for_active(
    db: Session,
    group_id: int,
) -> Dict[str, Dict[int, Decimal]]:
    """
    Возвращает net-балансы по валютам ТОЛЬКО для активных участников группы.
    Знак согласован со вкладкой «Баланс»:
      • net > 0 — пользователю ДОЛЖНЫ;
      • net < 0 — он ДОЛЖЕН.
    Учитываем только взаимодействия МЕЖДУ активными участниками.
    """
    member_ids = set(get_group_member_ids(db, group_id))
    if not member_ids:
        return {}

    txs = load_group_transactions(db, group_id)

    # ЕДИНЫЙ источник математики:
    from ..utils.balance import calculate_group_balances_by_currency
    nets_all = calculate_group_balances_by_currency(txs, member_ids)

    # Возвращаем только активных (на случай, если транзакции содержат исторических пользователей)
    out: Dict[str, Dict[int, Decimal]] = {}
    for code, per_user in nets_all.items():
        out[code] = {uid: per_user.get(uid, Decimal("0")) for uid in member_ids}
    return out


def has_group_debts(
    db: Session,
    group_id: int,
    * ,
    precision: float = 0.01,
) -> bool:
    """
    Проверка наличия долгов в группе среди АКТИВНЫХ участников.
    Мультивалютно (без межвалютного неттинга): достаточно,
    чтобы по ЛЮБОЙ валюте у ЛЮБОГО участника |net| > precision.
    """
    eps = _D(precision).copy_abs()
    nets = _nets_by_currency_for_active(db, group_id)
    if not nets:
        return False

    for per_ccy in nets.values():
        for value in per_ccy.values():
            if value.copy_abs() > eps:
                return True
    return False


def _member_nets(
    db: Session,
    group_id: int,
    user_id: int,
) -> Dict[str, Decimal]:
    """
    Возвращает словарь {currency_code: net} КОНКРЕТНОГО активного участника.
    Если пользователь не активен в группе — пустой словарь.
    """
    member_ids = set(get_group_member_ids(db, group_id))
    if user_id not in member_ids:
        return {}
    nets = _nets_by_currency_for_active(db, group_id)
    out: Dict[str, Decimal] = {}
    for code, per_user in nets.items():
        out[code] = per_user.get(user_id, Decimal("0"))
    return out


def ensure_member_can_leave(
    db: Session,
    group_id: int,
    user_id: int,
    * ,
    precision: float = 0.01,
) -> None:
    """
    Разрешаем выход из группы, если личный баланс пользователя ~ 0
    по КАЖДОЙ валюте среди активных участников.
    """
    group = require_membership(db, group_id, user_id)
    ensure_group_active(group)

    eps = _D(precision).copy_abs()
    nets = _member_nets(db, group_id, user_id)
    for value in nets.values():
        if value.copy_abs() > eps:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot leave the group while you still have unsettled balance.",
            )


def ensure_member_can_be_removed(
    db: Session,
    group_id: int,
    target_user_id: int,
    * ,
    precision: float = 0.01,
) -> None:
    """
    Разрешаем удаление участника, если его личный баланс ~ 0 по всем валютам.
    """
    eps = _D(precision).copy_abs()
    nets = _member_nets(db, group_id, target_user_id)
    for value in nets.values():
        if value.copy_abs() > eps:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Member has unsettled balance and cannot be removed.",
            )


def ensure_group_can_be_deleted(
    db: Session,
    group_id: int,
    * ,
    precision: float = 0.01,
) -> None:
    """
    Разрешаем удаление группы, если по АКТИВНЫМ участникам нет долгов.
    """
    # группа может быть уже помечена на удаление — достаем без фильтра
    get_group_or_404(db, group_id, include_deleted=True)

    if has_group_debts(db, group_id, precision=precision):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Group has unsettled balances and cannot be deleted.",
        )


# =========================
# ДОП. ХЕЛПЕРЫ ДЛЯ ДАШБОРДА
# =========================

def pick_last_currencies_for_user(
    db: Session,
    user_id: int,
    limit: int = 2,
) -> List[str]:
    """
    Две (или N) последних использованных пользователем валюты.
    Источник — транзакции пользователя или его доли (shares) через join на transactions.
    Учитываем исторические записи с is_deleted = NULL как «не удалённые».
    """
    # Через транзакции, где user — автор
    tx_currs = (
        db.execute(
            select(Transaction.currency_code, func.max(Transaction.date))
            .where(
                Transaction.created_by == user_id,
                or_(Transaction.is_deleted.is_(False), Transaction.is_deleted.is_(None)),
            )
            .group_by(Transaction.currency_code)
            .order_by(func.max(Transaction.date).desc())
            .limit(limit)
        )
        .all()
    )
    return [ccy for (ccy, _) in tx_currs]
