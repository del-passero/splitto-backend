# src/utils/groups.py
# ОБЩИЕ ХЕЛПЕРЫ ДЛЯ РАБОТЫ С ГРУППАМИ.
# Этот модуль НЕ завязан на конкретные роутеры — его задача дать единое место
# для проверок прав (участник/владелец), статуса группы (active/archived/deleted),
# и для типовых выборок (участники, разрешённые категории, наличие долгов).
#
# Зачем это нужно:
#  - Чтобы все роутеры (groups/transactions/group_members/...) использовали ОДНУ
#    и ту же логику проверок (никакого copy-paste).
#  - Чтобы при изменении бизнес-правил править один файл, а не все ручки.
#
# Важно: миграции для новых полей Group (status/archived_at/deleted_at/...) мы сделаем позже.
# Пока мы просто готовим код. Пожалуйста, не запускай приложение ДО миграций.

from __future__ import annotations

from typing import Callable, Iterable, Optional, Set, List
from datetime import datetime

from fastapi import HTTPException
from starlette import status
from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload

# Модели. Импорты завязаны на наши новые/старые модели.
from ..models.group import Group, GroupStatus
from ..models.group_member import GroupMember
from ..models.group_category import GroupCategory
from ..models.transaction import Transaction
# shares нам не нужны явно (берём через relationship), но оставляю комментарий на случай joinedload:
# from ..models.transaction_share import TransactionShare


# =========================
# БАЗОВЫЕ ПРОВЕРКИ/ВЫБОРКИ
# =========================

def get_group_or_404(db: Session, group_id: int, *, include_deleted: bool = False) -> Group:
    """
    Возвращает группу по ID или кидает 404.
    По умолчанию фильтрует soft-deleted группы (deleted_at IS NULL).
    """
    stmt = select(Group).where(Group.id == group_id)
    if not include_deleted:
        stmt = stmt.where(Group.deleted_at.is_(None))
    group = db.scalar(stmt)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


def require_membership(db: Session, group_id: int, user_id: int) -> Group:
    """
    Проверяет, что пользователь — участник группы. Возвращает ORM-объект группы.
    Кидает 403, если не участник, и 404 — если самой группы нет (или soft-deleted).
    """
    group = get_group_or_404(db, group_id)
    is_member = db.scalar(
        select(func.count())
        .select_from(GroupMember)
        .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )
    if not is_member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a group member")
    return group


def require_owner(db: Session, group_id: int, user_id: int) -> Group:
    """
    Проверяет, что пользователь — владелец группы. Возвращает ORM-объект группы.
    """
    group = get_group_or_404(db, group_id)
    if group.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner can perform this action")
    return group


def ensure_group_not_deleted(group: Group) -> None:
    """
    Кидает 409, если группа помечена как soft-deleted.
    """
    if group.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group is deleted")


def ensure_group_not_archived(group: Group) -> None:
    """
    Кидает 409, если группа в статусе archived.
    Архив = глобальное скрытие/заморозка: любые мутации запрещены.
    """
    if group.status == GroupStatus.archived:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group is archived")


def ensure_group_active(group: Group) -> None:
    """
    Быстрая проверка для мутирующих операций: группа не archived и не deleted.
    """
    ensure_group_not_deleted(group)
    ensure_group_not_archived(group)


# =========================
# ВЫБОРКИ ДЛЯ РОУТЕРОВ
# =========================

def get_group_member_ids(db: Session, group_id: int) -> List[int]:
    """
    Возвращает список user_id всех участников группы (без вложенных объектов).
    Один запрос — дёшево и быстро.
    """
    return [uid for (uid,) in db.execute(
        select(GroupMember.user_id).where(GroupMember.group_id == group_id)
    ).all()]


def load_group_transactions(db: Session, group_id: int) -> list[Transaction]:
    """
    Подгружает ВСЕ не удалённые транзакции группы с долями (joinedload(Transaction.shares)).
    Используем в расчётах балансов и любых агрегатах.
    """
    stmt = (
        select(Transaction)
        .where(
            Transaction.group_id == group_id,
            Transaction.is_deleted.is_(False),  # soft-delete транзакций
        )
        .options(joinedload(Transaction.shares))
        .order_by(Transaction.date.asc(), Transaction.id.asc())
    )
    return list(db.scalars(stmt).all())


# =========================
# ДОЛГИ / БАЛАНСЫ
# =========================

def has_group_debts(
    db: Session,
    group_id: int,
    *,
    precision: float = 0.01,
    calc_balances: Optional[Callable[..., dict[int, float]]] = None,
) -> bool:
    """
    Возвращает True, если в группе есть ЕЩЁ НЕ СВЕДЁННЫЕ долги (хотя бы у одного участника |баланс| > precision).
    По умолчанию использует твою функцию расчёта балансов (calculate_group_balances), если найдём её.
    Иначе можно подать свою функцию через параметр calc_balances.

    calc_balances ожидается со следующей сигнатурой:
        (member_ids: list[int], transactions: list[Transaction]) -> dict[user_id, balance]

    Почему так:
      - мы не дублируем логику расчёта балансов в двух местах (истина — одна).
      - уменьшаем риск расхождений с текущими ручками /groups/{id}/balances.
    """
    member_ids = get_group_member_ids(db, group_id)
    txs = load_group_transactions(db, group_id)

    balances: Optional[dict[int, float]] = None

    # 1) Если передали свою функцию — используем её.
    if calc_balances is not None:
        balances = calc_balances(member_ids, txs)

    # 2) Иначе пытаемся аккуратно импортировать твою реализацию из проекта (путь может отличаться).
    if balances is None:
        try:
            # Вариант 1: модуль рядом с роутерами (часто встречается)
            from ..balance import calculate_group_balances as _calc  # type: ignore
            balances = _calc(member_ids, txs)
        except Exception:
            try:
                # Вариант 2: внутри utils
                from ..utils.balance import calculate_group_balances as _calc  # type: ignore
                balances = _calc(member_ids, txs)
            except Exception:
                # Если не нашли — даём понятную ошибку с инструкцией.
                raise RuntimeError(
                    "Не удалось импортировать calculate_group_balances. "
                    "Передайте calc_balances=... или проверьте путь импорта (..balance или ..utils.balance)."
                )

    # 3) Проверяем, остались ли долги (балансы не все == 0).
    #    Считаем 'нет долгов', если |баланс| <= precision для каждого.
    for value in balances.values():
        if abs(value) > precision:
            return True
    return False


# =========================
# КАТЕГОРИИ ДЛЯ ГРУППЫ
# =========================

def get_allowed_category_ids(db: Session, group_id: int) -> Optional[Set[int]]:
    """
    Возвращает множество category_id, ДОПУЩЕННЫХ для этой группы.
    Если для группы НЕТ записей в group_categories — возвращаем None (означает «разрешены все глобальные»).
    Это решение удобнее пустого set(), потому что пустой set intuitively = «ничего нельзя».
    """
    rows = db.execute(
        select(GroupCategory.category_id).where(GroupCategory.group_id == group_id)
    ).all()
    if not rows:
        return None  # None == нет ограничений, т.е. разрешены все глобальные категории
    return {cid for (cid,) in rows}


def is_category_allowed(allowed_ids: Optional[Set[int]], category_id: Optional[int]) -> bool:
    """
    Проверяет, можно ли использовать category_id в этой группе.
    Правила:
      - Если ограничений нет (allowed_ids is None) — разрешаем любые глобальные категории.
      - Если ограничение есть — category_id должен входить в список.
      - Если category_id не указан (None) — считаем 'разрешено' (валидация обязательности — в схемах/роутере).
    """
    if category_id is None:
        return True
    if allowed_ids is None:
        return True
    return category_id in allowed_ids


# =========================
# УДОБНЫЕ ГАРДЫ ДЛЯ МУТАЦИЙ
# =========================

def guard_mutation_for_member(db: Session, group_id: int, user_id: int) -> Group:
    """
    Комплексная проверка для «обычных» мутирующих операций от участника:
      - группа существует и не soft-deleted,
      - пользователь — участник,
      - группа не archived.
    Возвращает ORM-объект группы (чтобы не загружать его дважды).
    """
    group = require_membership(db, group_id, user_id)
    ensure_group_active(group)
    return group


def guard_mutation_for_owner(db: Session, group_id: int, user_id: int) -> Group:
    """
    Комплексная проверка для мутирующих операций, доступных только владельцу:
      - группа существует и не soft-deleted,
      - пользователь — владелец,
      - группа не archived.
    Возвращает ORM-объект группы.
    """
    group = require_owner(db, group_id, user_id)
    ensure_group_active(group)
    return group
