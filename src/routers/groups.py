# backend/src/routers/groups.py
# -----------------------------------------------------------------------------
# РОУТЕР: Группы
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import List, Optional, Dict
from datetime import datetime, date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from starlette import status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, select, cast, or_
from sqlalchemy.sql.sqltypes import DateTime
from pydantic import BaseModel, constr  # AnyHttpUrl НЕ используем для входа, принимаем str

from src.db import get_db
from src.models.group import Group, GroupStatus, SettleAlgorithm
from src.models.group_member import GroupMember
from src.models.group_invite import GroupInvite
from src.models.user import User
from src.models.transaction import Transaction
from src.models.transaction_share import TransactionShare
from src.models.group_hidden import GroupHidden
from src.models.currency import Currency
from src.schemas.group import GroupCreate, GroupOut, GroupSettleAlgoEnum
from src.schemas.group_member import GroupMemberOut
from src.schemas.user import UserOut
from src.utils.telegram_dep import get_current_telegram_user
from src.utils.groups import (
    require_owner,
    ensure_group_active,
    has_group_debts,
)

from src.utils.media import (
    to_abs_media_url,
    url_to_media_local_path,
    delete_if_local,
)

router = APIRouter()

# ===== Вспомогательные =======================================================

def get_group_or_404(db: Session, group_id: int) -> Group:
    group = (
        db.query(Group)
        .filter(Group.id == group_id, Group.deleted_at.is_(None))
        .first()
    )
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    return group


def get_group_incl_deleted_or_404(db: Session, group_id: int) -> Group:
    """
    Возвращает группу без фильтра по deleted_at.
    Нужен для просмотра detail архивных/soft-удалённых групп.
    """
    group = db.query(Group).filter(Group.id == group_id).first()
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
    """
    ВАЖНО: учитываем старые записи с is_deleted = NULL как НЕ удалённые.
    """
    return (
        db.query(Transaction)
        .filter(
            Transaction.group_id == group_id,
            or_(Transaction.is_deleted.is_(False), Transaction.is_deleted.is_(None)),
        )
        .options(joinedload(Transaction.shares))
        .order_by(Transaction.date.asc(), Transaction.id.asc())
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


def _has_active_transactions(db: Session, group_id: int) -> bool:
    """
    Считаем активными и записи с is_deleted = NULL (наследие до миграций).
    """
    return db.query(Transaction.id).filter(
        Transaction.group_id == group_id,
        or_(Transaction.is_deleted.is_(False), Transaction.is_deleted.is_(None)),
    ).first() is not None


# ===== Балансы / Settle-up ====================================================

@router.get("/{group_id}/balances")
def get_group_balances(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    multicurrency: bool = Query(False, description="Вернуть балансы по каждой валюте отдельно"),
):
    # Разрешаем для archived и soft-deleted
    _require_membership_incl_deleted_group(db, group_id, current_user.id)
    group = get_group_incl_deleted_or_404(db, group_id)

    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)

    codes = sorted({(tx.currency_code or "").upper() for tx in transactions if tx.currency_code})
    decimals_map = {c.code: int(c.decimals) for c in db.query(Currency).filter(Currency.code.in_(codes)).all()}

    from src.utils.balance import calculate_group_balances_by_currency
    by_ccy = calculate_group_balances_by_currency(transactions, member_ids)

    if multicurrency:
        result: Dict[str, List[Dict[str, Decimal]]] = {}
        for code, balances in by_ccy.items():
            d = decimals_map.get(code, 2)
            result[code] = [{"user_id": uid, "balance": round(float(bal), d)} for uid, bal in balances.items()]
        return result

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
    algorithm: Optional[str] = Query(
        None,
        description="Переопределить алгоритм группы: 'greedy' (быстрый) | 'pairs' (попарный)",
    ),
):
    """
    План взаиморасчётов (settle-up).

    • Если указан ?algorithm=greedy|pairs — используем его.
      Иначе — берём алгоритм, сохранённый в группе.
    • При multicurrency=true отдаём dict по всем валютам: { "USD": [...], "EUR": [...] }.
      При multicurrency=false — список переводов только по default_currency_code группы.
    """
    # Разрешаем для archived и soft-deleted
    _require_membership_incl_deleted_group(db, group_id, current_user.id)
    group = get_group_incl_deleted_or_404(db, group_id)

    member_ids = get_group_member_ids(db, group_id)
    transactions = get_group_transactions(db, group_id)

    # карта точностей по валютам, присутствующим в транзакциях
    codes = sorted({(tx.currency_code or "").upper() for tx in transactions if tx.currency_code})
    decimals_map = {
        c.code: int(c.decimals)
        for c in db.query(Currency).filter(Currency.code.in_(codes)).all()
    }

    from src.utils.balance import (
        calculate_group_balances_by_currency,
        greedy_settle_up_single_currency,
        build_debts_matrix_by_currency,
        pairwise_settle_up_single_currency,
    )

    # Алгоритм: query-параметр переопределяет сохранённый в группе
    stored = (getattr(group, "settle_algorithm", None) or "greedy")
    if hasattr(stored, "value"):
        stored = stored.value
    algo = (algorithm or str(stored) or "greedy").lower().strip()
    if algo not in ("greedy", "pairs"):
        raise HTTPException(status_code=422, detail="algorithm must be 'greedy' or 'pairs'")

    # ----- MULTI-CURRENCY -----
    if multicurrency:
        if not transactions:
            return {}  # по всем валютам пусто

        if algo == "pairs":
            debts_by_ccy = build_debts_matrix_by_currency(transactions, member_ids)
            result: Dict[str, List[Dict]] = {}
            for code, matrix in debts_by_ccy.items():
                d = int(decimals_map.get(code, 2))
                result[code] = pairwise_settle_up_single_currency(matrix, d, currency_code=code)
            return result

        # greedy
        nets_by_ccy = calculate_group_balances_by_currency(transactions, member_ids)
        result: Dict[str, List[Dict]] = {}
        for code, balances in nets_by_ccy.items():
            d = int(decimals_map.get(code, 2))
            result[code] = greedy_settle_up_single_currency(balances, d, currency_code=code)
        return result

    # ----- SINGLE-CURRENCY (default группы) -----
    code = (group.default_currency_code or "").upper()
    if not transactions:
        return []  # по дефолтной валюте пусто

    if algo == "pairs":
        debts_by_ccy = build_debts_matrix_by_currency(transactions, member_ids)
        d = int(decimals_map.get(code, 2))
        matrix = debts_by_ccy.get(code, {})
        return pairwise_settle_up_single_currency(matrix, d, currency_code=code)

    # greedy
    nets_by_ccy = calculate_group_balances_by_currency(transactions, member_ids)
    balances = nets_by_ccy.get(code, {uid: Decimal("0") for uid in member_ids})
    d = int(decimals_map.get(code, 2))
    return greedy_settle_up_single_currency(balances, d, currency_code=code)

# ===== Создание и базовые списки ==============================================

@router.post("/", response_model=GroupOut)
def create_group(group: GroupCreate, db: Session = Depends(get_db)):
    # учитываем выбор settle_algorithm при создании (по умолчанию greedy)
    incoming = getattr(group.settle_algorithm, "value", None) or str(group.settle_algorithm or "greedy")
    db_group = Group(
        name=group.name,
        description=group.description,
        owner_id=group.owner_id,
        settle_algorithm=SettleAlgorithm(incoming.lower().strip()),
    )
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

# ===== Группы пользователя (пагинация + поиск + X-Total-Count) ===============

@router.get("/user/{user_id}")
def get_groups_for_user(
    user_id: int,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    request: Request = None,
    members_preview_limit: int = Query(4, gt=0),
    include_hidden: bool = Query(False, description="Включать персонально скрытые группы"),
    include_archived: bool = Query(False, description="Включать архивные группы"),
    include_deleted: bool = Query(False, description="Включать удалённые (soft-deleted) группы"),
    limit: int = Query(20, ge=1, le=200, description="Сколько групп вернуть"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации"),
    q: Optional[str] = Query(None, description="Поиск по названию/описанию"),
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

    base_q = db.query(Group).filter(Group.id.in_(user_group_ids))

    # по умолчанию удалённые не показываем
    if not include_deleted:
        base_q = base_q.filter(Group.deleted_at.is_(None))

    # архивные — по флагу
    if not include_archived:
        base_q = base_q.filter(Group.status == GroupStatus.active)

    # скрытые для клиента
    hidden_all_for_me = {
        gid for (gid,) in db.query(GroupHidden.group_id)
        .filter(GroupHidden.user_id == user_id)
        .all()
    }

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

    # Подзапрос last_tx_date (учитываем NULL в is_deleted)
    tx_dates_subq = (
        db.query(
            Transaction.group_id.label("g_id"),
            func.max(Transaction.date).label("last_tx_date"),
        )
        .filter(or_(Transaction.is_deleted.is_(False), Transaction.is_deleted.is_(None)))
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

    # Словарь last_activity_at (учитываем NULL в is_deleted)
    last_dates = dict(
        db.query(Transaction.group_id, func.max(Transaction.date))
        .filter(or_(Transaction.is_deleted.is_(False), Transaction.is_deleted.is_(None)),
                Transaction.group_id.in_(page_group_ids))
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
        is_hidden = group.id in hidden_all_for_me

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
            "is_hidden": is_hidden,
            # ---- аватар: отдаём абсолютный URL --------------------------------
            "avatar_url": to_abs_media_url(group.avatar_url, request),
        })

    return result

# ===== Детали группы (просмотр даже soft-deleted/archived) ====================

@router.get("/{group_id}/detail/", response_model=GroupOut)
def group_detail(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    request: Request = None,
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, gt=0)
):
    group = get_group_incl_deleted_or_404(db, group_id)
    _require_membership_incl_deleted_group(db, group_id, current_user.id)

    members_query = db.query(GroupMember).options(joinedload(GroupMember.user)).filter(
        GroupMember.group_id == group_id,
        GroupMember.deleted_at.is_(None),
    )
    members = members_query.offset(offset).limit(limit).all() if limit is not None else members_query.all()

    # Нормализуем аватар в абсолютный URL для ответа (БД не трогаем)
    if getattr(group, "avatar_url", None):
        group.avatar_url = to_abs_media_url(group.avatar_url, request)

    group.members = members
    return group

# ===== Персональное скрытие (разрешаем и для soft-deleted) ====================

@router.post("/{group_id}/hide", status_code=status.HTTP_204_NO_CONTENT)
def hide_group_for_me(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    _require_membership_incl_deleted_group(db, group_id, current_user.id)

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
    _require_membership_incl_deleted_group(db, group_id, current_user.id)

    row = db.query(GroupHidden).filter(
        GroupHidden.group_id == group_id,
        GroupHidden.user_id == current_user.id,
    ).first()
    if not row:
        return
    db.delete(row)
    db.commit()

# ===== Архивация (глобально) ==================================================

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

# ===== Soft-delete / Restore ===================================================

@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Удаление в один шаг:
      • если НЕТ транзакций и группа НЕ soft → жёстко удаляем сразу;
      • иначе, если НЕТ долгов → мягкое удаление (deleted_at=now);
      • иначе → 409.
    """
    group = require_owner(db, group_id, current_user.id)

    # Нельзя удалять архивную группу (сначала разархивировать)
    if group.status == GroupStatus.archived:
        raise HTTPException(status_code=409, detail="Группа архивирована")

    has_tx = _has_active_transactions(db, group_id)
    has_debts_flag = has_group_debts(db, group_id)

    # Если нет активных транзакций и НЕ soft → hard сразу
    if not has_tx and group.deleted_at is None:
        if has_debts_flag:
            raise HTTPException(status_code=409, detail="В группе есть непогашенные долги")
        _hard_delete_group_impl(db, group_id)
        return

    # Если есть активные транзакции — проверяем долги, затем soft
    if has_debts_flag:
        raise HTTPException(status_code=409, detail="В группе есть непогашенные долги")

    if group.deleted_at is None:
        group.deleted_at = datetime.utcnow()
        db.commit()
    else:
        # уже soft — ничего не делаем
        return


@router.post("/{group_id}/restore")
def restore_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    to_active: bool = Query(False, description="(ignored)"),
    return_full: bool = Query(False, description="Вернуть полную модель GroupOut вместо 204"),
):
    """
    Восстановление из soft: всегда в ACTIVE (без промежуточной 'archived').
    """
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
    group.status = GroupStatus.active
    group.archived_at = None
    db.commit()
    if return_full:
        db.refresh(group)
        return GroupOut.from_orm(group)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# ===== Hard-delete ============================================================

def _hard_delete_group_impl(db: Session, group_id: int):
    """
    Жёсткое удаление зависимостей + самой группы. После успешного commit
    пробуем удалить локальный файл аватара (если был и если локальный).

    NB: сюда можно прийти как из DELETE /{id}/hard, так и из soft-delete,
    когда активных транзакций нет (остались только soft-удалённые).
    """
    # Сохраним текущий аватар до удаления записи
    group_row: Optional[Group] = db.query(Group).filter(Group.id == group_id).first()
    avatar_url_before = getattr(group_row, "avatar_url", None) if group_row else None

    # 1) Сначала чистим шейры → транзакции (чтобы не ловить FK на transactions.group_id)
    tx_ids = [tid for (tid,) in db.query(Transaction.id).filter(Transaction.group_id == group_id).all()]
    if tx_ids:
        db.query(TransactionShare).filter(TransactionShare.transaction_id.in_(tx_ids)).delete(synchronize_session=False)
        db.query(Transaction).filter(Transaction.id.in_(tx_ids)).delete(synchronize_session=False)

    # 2) Прочие зависимости группы
    db.query(GroupHidden).filter(GroupHidden.group_id == group_id).delete(synchronize_session=False)
    db.query(GroupInvite).filter(GroupInvite.group_id == group_id).delete(synchronize_session=False)
    db.query(GroupMember).filter(GroupMember.group_id == group_id).delete(synchronize_session=False)

    # 3) Сама группа
    db.query(Group).filter(Group.id == group_id).delete(synchronize_session=False)
    db.commit()

    # После успешного commit — пытаемся удалить локальный файл (только из group_avatars)
    delete_if_local(avatar_url_before, allowed_subdirs=("group_avatars",))


@router.delete("/{group_id}/hard", status_code=status.HTTP_204_NO_CONTENT)
def hard_delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Жёсткое удаление:
      • только владелец,
      • разрешено для активных/архивных/скрытых,
      • запрещено для soft-deleted (сначала restore),
      • только если нет активных транзакций и долгов.
    """
    group = require_owner(db, group_id, current_user.id)

    # Нельзя удалять архивную группу (сначала разархивировать)
    if group.status == GroupStatus.archived:
        raise HTTPException(status_code=409, detail="Группа архивирована")

    # Если группа уже soft — запрещаем
    if group.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Сначала восстановите группу из удалённых (soft)")

    if _has_active_transactions(db, group_id):
        raise HTTPException(status_code=409, detail="В группе есть транзакции — жёсткое удаление запрещено")

    if has_group_debts(db, group_id):
        raise HTTPException(status_code=409, detail="В группе есть непогашенные долги")

    _hard_delete_group_impl(db, group_id)

# ===== Смена валюты группы ====================================================

@router.patch("/{group_id}/currency", status_code=status.HTTP_204_NO_CONTENT)
def change_group_currency(
    group_id: int,
    code: str = Query(..., min_length=3, max_length=3),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    # Только для активной группы
    group = get_group_or_404(db, group_id)
    _require_membership_incl_deleted_group(db, group_id, current_user.id)
    ensure_group_active(group)

    norm_code = code.upper().strip()
    cur = db.scalar(select(Currency).where(Currency.code == norm_code, Currency.is_active.is_(True)))
    if not cur:
        raise HTTPException(status_code=404, detail="Currency not found or inactive")

    group.default_currency_code = norm_code
    db.commit()

# ===== Смена алгоритма settle-up (любой участник активной группы) ============

class SettleAlgorithmUpdate(BaseModel):
    settle_algorithm: GroupSettleAlgoEnum

@router.patch("/{group_id}/settle-algorithm")
def update_group_settle_algorithm(
    group_id: int,
    payload: SettleAlgorithmUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    return_full: bool = Query(False, description="Вернуть полную модель GroupOut вместо 204"),
):
    """
    Меняет алгоритм взаимозачёта для группы:
      • любой активный участник,
      • только для ACTIVE группы,
      • значения: greedy | pairs.
    """
    group = get_group_or_404(db, group_id)
    _require_membership_incl_deleted_group(db, group_id, current_user.id)
    ensure_group_active(group)

    new_algo = SettleAlgorithm(
        payload.settle_algorithm.value
        if hasattr(payload.settle_algorithm, "value")
        else str(payload.settle_algorithm).lower().strip()
    )

    if group.settle_algorithm != new_algo:
        group.settle_algorithm = new_algo
        db.commit()

    if return_full:
        db.refresh(group)
        return GroupOut.from_orm(group)

    return Response(status_code=status.HTTP_204_NO_CONTENT)

# ===== Аватар группы: установка по URL (любой участник активной группы) ======

class AvatarUrlIn(BaseModel):
    # принимаем любую непустую строку; относительную превратим в абсолютную
    url: constr(strip_whitespace=True, min_length=1)

@router.post("/{group_id}/avatar/url", response_model=GroupOut)
def set_group_avatar_by_url(
    group_id: int,
    payload: AvatarUrlIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    request: Request = None,
):
    group = get_group_or_404(db, group_id)
    _require_membership_incl_deleted_group(db, group_id, current_user.id)
    ensure_group_active(group)

    # запомним старый аватар, чтобы удалить файл (если локальный) после замены
    old_url = group.avatar_url

    absolute_url = to_abs_media_url(payload.url, request)
    group.avatar_url = str(absolute_url)
    group.avatar_file_id = None
    group.avatar_updated_at = datetime.utcnow()
    db.commit()
    db.refresh(group)

    # Если старый файл был локальным и отличается от нового — удаляем его из ФС
    try:
        old_local = url_to_media_local_path(old_url, allowed_subdirs=("group_avatars",))
        new_local = url_to_media_local_path(group.avatar_url, allowed_subdirs=("group_avatars",))
        if old_local and (not new_local or old_local != new_local):
            delete_if_local(old_url, allowed_subdirs=("group_avatars",))
    except Exception:
        pass

    # Отдаём уже нормализованное абсолютное
    group.avatar_url = to_abs_media_url(group.avatar_url, request)
    return group

# ===== Аватар группы: удаление (любой участник активной группы) ==============

@router.delete("/{group_id}/avatar", status_code=status.HTTP_204_NO_CONTENT)
def delete_group_avatar(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    group = get_group_or_404(db, group_id)
    _require_membership_incl_deleted_group(db, group_id, current_user.id)
    ensure_group_active(group)

    # сохраним, чтобы удалить файл после обнуления полей
    old_url = group.avatar_url

    group.avatar_url = None
    group.avatar_file_id = None
    group.avatar_updated_at = datetime.utcnow()
    db.commit()

    # пытаемся удалить локальный файл (если он из нашего /media/group_avatars)
    delete_if_local(old_url, allowed_subdirs=("group_avatars",))

# ===== Расписание (end_date / auto_archive) ===================================

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
    group = get_group_or_404(db, group_id)
    _require_membership_incl_deleted_group(db, group_id, current_user.id)
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
    Доступ: любой участник. Только для активной группы.
    """
    group = get_group_or_404(db, group_id)
    _require_membership_incl_deleted_group(db, group_id, current_user.id)
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

# ===== Батч-превью долгов для карточек =======================================

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
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        ids: List[int] = [int(x) for x in group_ids.split(",") if x.strip()]
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid group_ids")

    if not ids:
        return {}

    result: Dict[str, Dict[str, Dict[str, float]]] = {}
    from src.utils.balance import calculate_group_balances_by_currency
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
        decimals_map = {c.code: int(c.decimals) for c in db.query(Currency).filter(Currency.code.in_(codes)).all() }
        by_ccy = calculate_group_balances_by_currency(txs, members)

        owe: Dict[str, float] = {}
        owed: Dict[str, float] = {}
        for code, balances in by_ccy.items():
            bal = float(balances.get(current_user.id, Decimal("0")))
            d = decimals_map.get(code, 2)
            if bal < 0:
                owe[code] = round(abs(bal), d)
            elif bal > 0:
                owed[code] = round(bal, d)
        result[str(gid)] = {"owe": owe, "owed": owed}

    return result


# ===== Внутренние проверки членства (оставлены без изменений) =================

def _require_membership_incl_deleted_group(db: Session, group_id: int, user_id: int) -> None:
    """
    Проверяем, что пользователь состоит в группе (активный membership),
    даже если группа archived/soft-deleted.
    """
    is_member = db.query(GroupMember.id).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == user_id,
        GroupMember.deleted_at.is_(None)
    ).first()
    if not is_member:
        raise HTTPException(status_code=403, detail="Forbidden")
