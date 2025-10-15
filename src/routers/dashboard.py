# src/routers/dashboard.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional, Dict, List

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session, aliased

from src.db import get_db
from src.utils.telegram_dep import get_current_telegram_user
from src.models.transaction import Transaction
from src.models.transaction_share import TransactionShare
from src.models.group import Group, GroupStatus
from src.models.group_member import GroupMember
from src.models.expense_category import ExpenseCategory
from src.models.event import Event
from src.models.user import User
from src.schemas.dashboard import (
    DashboardBalanceOut,
    DashboardActivityOut,
    ActivityBucketOut,
    TopCategoriesOut,
    TopCategoryItemOut,
    DashboardSummaryOut,
    RecentGroupCardOut,
    TopPartnerItemOut,
    EventsFeedOut,
    EventFeedItemOut,
)

# --- единые утилиты и математика из проекта ---
from src.utils.groups import (
    get_group_member_ids,
    load_group_transactions,
    pick_last_currencies_for_user,
)
from src.utils.balance import calculate_group_balances_by_currency


router = APIRouter()

# =========================
# Вспомогательные штуки
# =========================

def _period_to_range(today: date, period: Literal["day", "week", "month", "year"]) -> tuple[date, date]:
    if period == "day":
        start = today
    elif period == "week":
        start = today - timedelta(days=6)
    elif period == "month":
        start = today.replace(day=1)
    else:
        start = date(today.year, 1, 1)
    end = today + timedelta(days=1)
    return start, end


def _active_group_ids_for_user(db: Session, user_id: int) -> list[int]:
    rows = db.execute(
        select(GroupMember.group_id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(
            GroupMember.user_id == user_id,
            GroupMember.deleted_at.is_(None),
            Group.deleted_at.is_(None),
            Group.status == GroupStatus.active,
        )
    ).all()
    return [gid for (gid,) in rows]


# исторические NULL считаем «не удалено» — как на вкладке баланса
def _is_active_tx():
    return or_(Transaction.is_deleted.is_(False), Transaction.is_deleted.is_(None))


# Валютные деноминации (для округления и eps)
_DECIMALS: Dict[str, int] = {
    # без копеек
    "JPY": 0, "KRW": 0, "HUF": 0, "VND": 0, "CLP": 0, "ISK": 0,
    # три знака
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
    # экзотика
    "CLF": 4,
}
DEF_DECIMALS = 2

def _decimals_for(ccy: str) -> int:
    return int(_DECIMALS.get((ccy or "").upper(), DEF_DECIMALS))

def _q(decimals: int) -> Decimal:
    return Decimal("1") if decimals <= 0 else Decimal("1").scaleb(-decimals)

def _round(d: Decimal, decimals: int) -> Decimal:
    return d.quantize(_q(decimals), rounding=ROUND_HALF_UP)

def _eps_for(decimals: int) -> Decimal:
    # минимально — 1e-2 как в utils.balance._eps
    return Decimal("1").scaleb(-max(decimals, 2))

def _D(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


# =========================
# /dashboard/balance  — ВАРИАНТ A
# =========================
@router.get("/balance", response_model=DashboardBalanceOut)
def get_dashboard_balance(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    """
    Глобальный баланс пользователя по ВСЕМ активным группам:
    • считаем net по каждой группе той же математикой, что и вкладка «Баланс»;
    • суммируем net пользователя по валютам;
      net>0 → they_owe_me[ccy] += net
      net<0 → i_owe[ccy]      += -net
    • округляем по деноминации, режем «пыль» (eps), коды валют — UPPERCASE.
    """
    user_id = int(current_user.id)
    group_ids = _active_group_ids_for_user(db, user_id)
    if not group_ids:
        return DashboardBalanceOut(i_owe={}, they_owe_me={}, last_currencies=[])

    they_owe_me_acc: Dict[str, Decimal] = {}
    i_owe_acc: Dict[str, Decimal] = {}

    for gid in group_ids:
        # активные участники в группе
        member_ids = get_group_member_ids(db, gid)
        if not member_ids or user_id not in member_ids:
            continue

        # только не удалённые транзакции + shares (как в группе)
        txs = load_group_transactions(db, gid)
        if not txs:
            continue

        nets_by_ccy = calculate_group_balances_by_currency(txs, member_ids)
        for code, per_user in nets_by_ccy.items():
            ccy = (code or "").upper() or "XXX"
            net = _D(per_user.get(user_id, Decimal("0")))
            if not net:
                continue

            decs = _decimals_for(ccy)
            eps = _eps_for(decs)

            if net > eps:
                # мне должны
                they_owe_me_acc[ccy] = they_owe_me_acc.get(ccy, Decimal("0")) + net
            elif net < -eps:
                # я должен (храним в аккумуляторе положительным числом — модуль)
                i_owe_acc[ccy] = i_owe_acc.get(ccy, Decimal("0")) + (-net)

    # Округление и отбрасывание «пыли»
    they_owe_me_str: Dict[str, str] = {}
    for ccy, amt in they_owe_me_acc.items():
        decs = _decimals_for(ccy)
        eps = _eps_for(decs)
        v = _round(amt, decs)
        if v.copy_abs() > eps:
            # по примеру из твоей схемы оставляю «+»
            sign = "+" if v >= 0 else "-"
            they_owe_me_str[ccy] = f"{sign}{abs(v):.{decs}f}"

    i_owe_str: Dict[str, str] = {}
    for ccy, amt in i_owe_acc.items():
        decs = _decimals_for(ccy)
        eps = _eps_for(decs)
        v = _round(amt, decs)
        if v.copy_abs() > eps:
            # здесь всегда должен быть минус — это «я должен»
            i_owe_str[ccy] = f"-{abs(v):.{decs}f}"

    # Последние валюты пользователя (как у тебя в utils)
    last_currencies = pick_last_currencies_for_user(db, user_id, limit=2)

    return DashboardBalanceOut(
        i_owe=i_owe_str,
        they_owe_me=they_owe_me_str,
        last_currencies=[(c or "").upper() for c in last_currencies],
    )


# =========================
# /dashboard/activity
# =========================
@router.get("/activity", response_model=DashboardActivityOut)
def get_dashboard_activity(
    period: Literal["day", "week", "month", "year"] = Query("month"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    today = date.today()
    d_from, d_to = _period_to_range(today, period)
    group_ids = _active_group_ids_for_user(db, current_user.id)
    if not group_ids:
        return DashboardActivityOut(period=period, buckets=[])

    rows = db.execute(
        select(Transaction.date, func.count(Transaction.id))
        .where(
            Transaction.group_id.in_(group_ids),
            _is_active_tx(),
            Transaction.type == "expense",
            Transaction.date >= d_from,
            Transaction.date < d_to,
        )
        .group_by(Transaction.date)
        .order_by(Transaction.date.asc())
    ).all()

    buckets = [ActivityBucketOut(date=d, count=c) for (d, c) in rows]
    return DashboardActivityOut(period=period, buckets=buckets)


# =========================
# /dashboard/top-categories
# =========================
def _parse_accept_language(header: str | None) -> list[str]:
    if not header:
        return []
    parts: list[tuple[str, float]] = []
    for chunk in header.split(","):
        item = chunk.strip()
        if not item:
            continue
        lang, *qpart = item.split(";")
        base = lang.strip().lower().split("-")[0]
        q = 1.0
        if qpart:
            try:
                q = float(qpart[0].split("=")[1])
            except Exception:
                pass
        parts.append((base, q))
    seen: set[str] = set()
    out: list[str] = []
    for base, _q in sorted(parts, key=lambda x: x[1], reverse=True):
        if base not in seen:
            seen.add(base)
            out.append(base)
    return out

@router.get("/top-categories", response_model=TopCategoriesOut)
def get_top_categories(
    request: Request,
    period: Literal["week", "month", "year"] = Query("month"),
    currency: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    locale: Optional[str] = Query(None, description="Приоритетная локаль для имени категории (ru/en/es)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    today = date.today()
    d_from, d_to = _period_to_range(today, period)
    group_ids = _active_group_ids_for_user(db, current_user.id)
    if not group_ids:
        return TopCategoriesOut(period=period, items=[], total=0)

    # Приоритет локалей: ?locale → user.locale → Accept-Language → en,ru,es
    locales: list[str] = []
    if locale:
        locales.append(str(locale).split("-")[0].lower())
    user_locale = getattr(current_user, "locale", None)
    if user_locale:
        locales.append(str(user_locale).split("-")[0].lower())
    locales += _parse_accept_language(request.headers.get("Accept-Language"))
    for fb in ("en", "ru", "es"):
        if fb not in locales:
            locales.append(fb)
    seen: set[str] = set()
    locales = [x for x in locales if not (x in seen or seen.add(x))]
    if not locales:
        locales = ["en"]

    where_clause = [
        Transaction.group_id.in_(group_ids),
        _is_active_tx(),
        Transaction.type == "expense",
        Transaction.date >= d_from,
        Transaction.date < d_to,
    ]
    if currency:
        where_clause.append(Transaction.currency_code == currency)

    # Локализованное имя
    name_candidates = [ExpenseCategory.name_i18n[loc].astext for loc in locales]
    cat_name_expr = func.coalesce(*name_candidates, ExpenseCategory.key).label("name")

    sum_amount = func.sum(Transaction.amount).label("sum_amount")

    # Цвет категории: берём цвет самой категории, если нет — цвет родителя
    Parent = aliased(ExpenseCategory)
    color_expr = func.coalesce(ExpenseCategory.color, Parent.color).label("color")

    base = (
        select(
            Transaction.category_id.label("category_id"),
            cat_name_expr,
            Transaction.currency_code.label("currency"),
            sum_amount,
            ExpenseCategory.icon.label("icon"),
            color_expr,
        )
        .join(ExpenseCategory, ExpenseCategory.id == Transaction.category_id)
        .outerjoin(Parent, Parent.id == ExpenseCategory.parent_id)
        .where(and_(*where_clause))
        .group_by(
            Transaction.category_id,
            cat_name_expr,
            Transaction.currency_code,
            ExpenseCategory.icon,
            ExpenseCategory.color,
            Parent.color,
        )
        .order_by(desc(sum_amount))
    )

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0
    rows = db.execute(base.offset(offset).limit(limit)).all()

    items = [
        TopCategoryItemOut(
            category_id=row.category_id,
            name=row.name,
            sum=f"{(row.sum_amount or 0):.2f}",
            currency=row.currency,
            icon=row.icon,
            color=row.color,
        )
        for row in rows
    ]
    return TopCategoriesOut(period=period, items=items, total=int(total))


# =========================
# /dashboard/summary
# =========================
@router.get("/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(
    period: Literal["day", "week", "month", "year"] = Query("month"),
    currency: str = Query(..., min_length=3, max_length=3),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    today = date.today()
    d_from, d_to = _period_to_range(today, period)
    group_ids = _active_group_ids_for_user(db, current_user.id)
    if not group_ids:
        return DashboardSummaryOut(period=period, currency=currency, spent="0.00", avg_check="0.00", my_share="0.00")

    spent_sum, avg_check = db.execute(
        select(func.sum(Transaction.amount), func.avg(Transaction.amount))
        .where(
            Transaction.group_id.in_(group_ids),
            _is_active_tx(),
            Transaction.type == "expense",
            Transaction.currency_code == currency,
            Transaction.date >= d_from,
            Transaction.date < d_to,
        )
    ).one() or (0, 0)

    my_share_sum = db.execute(
        select(func.sum(TransactionShare.amount))
        .join(Transaction, Transaction.id == TransactionShare.transaction_id)
        .where(
            Transaction.group_id.in_(group_ids),
            _is_active_tx(),
            Transaction.type == "expense",
            Transaction.currency_code == currency,
            Transaction.date >= d_from,
            Transaction.date < d_to,
            TransactionShare.user_id == current_user.id,
        )
    ).scalar() or 0

    return DashboardSummaryOut(
        period=period,
        currency=currency,
        spent=f"{spent_sum or 0:.2f}",
        avg_check=f"{avg_check or 0:.2f}",
        my_share=f"{my_share_sum or 0:.2f}",
    )


# =========================
# /dashboard/recent-groups
# =========================
@router.get("/recent-groups", response_model=list[RecentGroupCardOut])
def get_recent_groups(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    rows = db.execute(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(
            GroupMember.user_id == current_user.id,
            GroupMember.deleted_at.is_(None),
            Group.deleted_at.is_(None),
            Group.status == GroupStatus.active,
        )
        .order_by(
            Group.last_event_at.desc().nullslast(),
            Group.id.desc(),
        )
        .limit(limit)
    ).scalars().all()

    out: list[RecentGroupCardOut] = []
    for g in rows:
        sums = db.execute(
            select(Transaction.currency_code, func.sum(TransactionShare.amount))
            .join(Transaction, Transaction.id == TransactionShare.transaction_id)
            .where(
                Transaction.group_id == g.id,
                _is_active_tx(),
                TransactionShare.user_id == current_user.id,
            )
            .group_by(Transaction.currency_code)
        ).all()
        my_balance = { (ccy or "").upper(): f"{(s or 0):.2f}" for (ccy, s) in sums }
        out.append(
            RecentGroupCardOut(
                id=g.id,
                name=g.name,
                avatar_url=g.avatar_url,
                my_balance_by_currency=my_balance,
                last_event_at=g.last_event_at,
            )
        )
    return out


# =========================
# /dashboard/top-partners
# =========================
@router.get("/top-partners", response_model=list[TopPartnerItemOut])
def get_top_partners(
    period: Literal["week", "month", "year"] = Query("month"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    today = date.today()
    d_from, d_to = _period_to_range(today, period)
    group_ids = _active_group_ids_for_user(db, current_user.id)
    if not group_ids:
        return []

    tx_ids_with_me = (
        select(TransactionShare.transaction_id)
        .join(Transaction, Transaction.id == TransactionShare.transaction_id)
        .where(
            Transaction.group_id.in_(group_ids),
            _is_active_tx(),
            Transaction.type == "expense",
            Transaction.date >= d_from,
            Transaction.date < d_to,
            TransactionShare.user_id == current_user.id,
        )
        .subquery()
    )

    other_counts = (
        select(TransactionShare.user_id, func.count(func.distinct(TransactionShare.transaction_id)).label("cnt"))
        .where(
            TransactionShare.transaction_id.in_(select(tx_ids_with_me)),
            TransactionShare.user_id != current_user.id,
        )
        .group_by(TransactionShare.user_id)
        .order_by(desc("cnt"))
        .limit(limit)
        .subquery()
    )

    rows = db.execute(select(User, other_counts.c.cnt).join(other_counts, other_counts.c.user_id == User.id)).all()
    return [
        TopPartnerItemOut(user=user, joint_expense_count=int(cnt or 0), period=period)
        for user, cnt in rows
    ]


# =========================
# /dashboard/last-currencies
# =========================
@router.get("/last-currencies", response_model=list[str])
def get_last_currencies(
    limit: int = Query(2, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    return [ (c or "").upper() for c in pick_last_currencies_for_user(db, current_user.id, limit=limit) ]


# =========================
# /dashboard/events — UI-friendly
# =========================
@router.get("/events", response_model=EventsFeedOut)
def get_ui_events_feed(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    rows = db.execute(
        select(Event)
        .where(
            or_(
                Event.actor_id == current_user.id,
                Event.target_user_id == current_user.id,
            )
        )
        .order_by(Event.created_at.desc())
        .limit(limit)
    ).scalars().all()

    items: list[EventFeedItemOut] = []
    for e in rows:
        t = e.type or ""
        data = e.data or {}
        title = t
        subtitle = None
        icon = "Bell"
        entity = {}

        if t == "transaction_created":
            icon = "PlusCircle"
            title = "Добавлена новая транзакция"
            entity = {"kind": "transaction", "id": data.get("transaction_id")}
            if data.get("amount"):
                subtitle = f"{data['amount']} {data.get('currency','')}"
        elif t == "transaction_updated":
            icon = "Edit"
            title = "Изменена транзакция"
            entity = {"kind": "transaction", "id": data.get("transaction_id")}
        elif t == "group_created":
            icon = "Users"
            title = "Создана группа"
            entity = {"kind": "group", "id": e.group_id}
        elif t == "group_archived":
            icon = "Archive"
            title = "Группа архивирована"
            entity = {"kind": "group", "id": e.group_id}
        elif t == "member_added":
            icon = "UserPlus"
            title = "Добавлен участник"
            entity = {"kind": "group", "id": e.group_id}
        elif t == "member_removed":
            icon = "UserMinus"
            title = "Удалён участник"
            entity = {"kind": "group", "id": e.group_id}
        elif t == "receipt_uploaded":
            icon = "FileText"
            title = "Загружен чек"
            entity = {"kind": "transaction", "id": data.get("transaction_id")}

        items.append(
            EventFeedItemOut(
                id=e.id,
                type=t,
                created_at=e.created_at,
                title=title,
                subtitle=subtitle,
                icon=icon,
                entity=entity,
            )
        )

    return EventsFeedOut(items=items)
