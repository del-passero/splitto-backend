# src/utils/groups.py
# ОБЩИЕ ХЕЛПЕРЫ ДЛЯ РАБОТЫ С ГРУППАМИ.

from __future__ import annotations

from typing import Callable, Iterable, Optional, Set, List
from datetime import datetime

from fastapi import HTTPException
from starlette import status
from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload

from ..models.group import Group, GroupStatus
from ..models.group_member import GroupMember
from ..models.group_category import GroupCategory
from ..models.transaction import Transaction


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


def load_group_transactions(db: Session, group_id: int) -> list[Transaction]:
    """
    Загружает активные транзакции группы с подгруженными долями.
    ВНИМАНИЕ: используется joinedload на коллекции, поэтому
    необходимо вызвать .unique() на Result перед .scalars().
    """
    stmt = (
        select(Transaction)
        .where(
            Transaction.group_id == group_id,
            Transaction.is_deleted.is_(False),
        )
        .options(joinedload(Transaction.shares))
        .order_by(Transaction.date.asc(), Transaction.id.asc())
    )
    # Критическая правка: execute(...).unique().scalars().all()
    return db.execute(stmt).unique().scalars().all()


def has_group_debts(
    db: Session,
    group_id: int,
    *,
    precision: float = 0.01,
    calc_balances: Optional[Callable[..., dict[int, float]]] = None,
) -> bool:
    """
    Историческая проверка (single-currency). Оставляем как есть для архивирования группы.
    """
    member_ids = get_group_member_ids(db, group_id)
    txs = load_group_transactions(db, group_id)

    balances: Optional[dict[int, float]] = None
    if calc_balances is not None:
        balances = calc_balances(member_ids, txs)
    if balances is None:
        try:
            from ..balance import calculate_group_balances as _calc  # type: ignore
            balances = _calc(member_ids, txs)
        except Exception:
            try:
                from ..utils.balance import calculate_group_balances as _calc  # type: ignore
                balances = _calc(member_ids, txs)
            except Exception:
                raise RuntimeError(
                    "Не удалось импортировать calculate_group_balances. "
                    "Передайте calc_balances=... или проверьте путь импорта."
                )

    for value in balances.values():
        if abs(value) > precision:
            return True
    return False


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


def guard_mutation_for_member(db: Session, group_id: int, user_id: int) -> Group:
    group = require_membership(db, group_id, user_id)
    ensure_group_active(group)
    return group


def guard_mutation_for_owner(db: Session, group_id: int, user_id: int) -> Group:
    group = require_owner(db, group_id, user_id)
    ensure_group_active(group)
    return group
