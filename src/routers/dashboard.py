# src/routers/dashboard.py
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, Optional, Sequence

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import nulls_last  # для корректного ORDER BY ... NULLS LAST

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

from src.utils.groups import pick_last_currencies_for_user

router = APIRouter()


# ------------------ helpers ------------------

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


def _parse_accept_language(header: str | None) -> list[str]:
    """
    Примерно разбирает 'ru-RU,ru;q=0.9,en;q=0.8' -> ['ru', 'en'] (по убыванию q).
    Упрощённо: вырезает регион и сортирует по q. Возвращает уникальные базовые коды.
    """
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


# ------------------ /dashboard/balance ------------------

@router.get("/balance", response_model=DashboardBalanceOut)
def get_dashboard_balance(
    currencies: Optional[Sequence[str]] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    group_ids = _active_group_ids_for_user(db, current_user.id)
    if not group_ids:
        return DashboardBalanceOut(i_owe={}, they_owe_me={}, last_currencies=[])

    q = (
        select(Transaction.currency_code, func.sum(TransactionShare.amount))
        .select_from(TransactionShare)
        .join(Transaction, Transaction.id == TransactionShare.transaction_id)
        .where(
            Transaction.group_id.in_(group_ids),
            Transaction.is_deleted.is_(False),
            TransactionShare.user_id == current_user.id,
        )
        .group_by(Transaction.currency_code)
    )
    if currencies:
        q = q.where(Transaction.currency_code.in_(currencies))

    rows = db.execute(q).all()
    i_owe: dict[str, str] = {}
    they_owe_me: dict[str, str] = {}
    for ccy, s in rows:
        s = s or 0
        if s >= 0:
            they_owe_me[ccy] = f"{s:.2f}"
        else:
            i_owe[ccy] = f"{s:.2f}"

    last_currencies = pick_last_currencies_for_user(db, current_user.id, limit=2)
    return DashboardBalanceOut(i_owe=i_owe, they_owe_me=they_owe_me, last_currencies=last_currencies)


# ------------------ /dashboard/activity ------------------

@router.get("/activity", response_model=DashboardActivityOut)
def get_dashboard_activity(
    period: Literal["week", "month", "year"] = Query("month"),
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
            Transaction.is_deleted.is_(False),
            Transaction.date >= d_from,
            Transaction.date < d_to,
        )
        .group_by(Transaction.date)
        .order_by(Transaction.date.asc())
    ).all()

    buckets = [ActivityBucketOut(date=d, count=c) for (d, c) in rows]
    return DashboardActivityOut(period=period, buckets=buckets)


# ------------------ /dashboard/top-categories ------------------

@router.get("/top-categories", response_model=TopCategoriesOut)
def get_top_categories(
    request: Request,
    period: Literal["week", "month", "year"] = Query("month"),
    currency: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    today = date.today()
    d_from, d_to = _period_to_range(today, period)
    group_ids = _active_group_ids_for_user(db, current_user.id)
    if not group_ids:
        return TopCategoriesOut(period=period, items=[], total=0)

    # Локали по приоритету: user.locale -> Accept-Language -> дефолты
    locales: list[str] = []
    user_locale = getattr(current_user, "locale", None)
    if user_locale:
        locales.append(str(user_locale).split("-")[0].lower())
    locales += _parse_accept_language(request.headers.get("Accept-Language"))
    for fb in ("en", "ru", "es"):
        if fb not in locales:
            locales.append(fb)
    # уникализация с сохранением порядка
    seen: set[str] = set()
    locales = [x for x in locales if not (x in seen or seen.add(x))]
    if not locales:
        locales = ["en"]

    where_clause = [
        Transaction.group_id.in_(group_ids),
        Transaction.is_deleted.is_(False),
        Transaction.type == "expense",
        Transaction.date >= d_from,
        Transaction.date < d_to,
    ]
    if currency:
        where_clause.append(Transaction.currency_code == currency)

    # COALESCE(name_i18n['xx']::text, ..., key) AS name
    name_candidates = [ExpenseCategory.name_i18n[loc].astext for loc in locales]
    cat_name_expr = func.coalesce(*name_candidates, ExpenseCategory.key).label("name")

    sum_amount = func.sum(Transaction.amount).label("sum_amount")

    base = (
        select(
            Transaction.category_id.label("category_id"),
            cat_name_expr,  # важно — тот же expr в GROUP BY
            Transaction.currency_code.label("currency"),
            sum_amount,
        )
        .join(ExpenseCategory, ExpenseCategory.id == Transaction.category_id)
        .where(and_(*where_clause))
        .group_by(
            Transaction.category_id,
            cat_name_expr,
            Transaction.currency_code,
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
        )
        for row in rows
    ]
    return TopCategoriesOut(period=period, items=items, total=int(total))


# ------------------ /dashboard/summary ------------------

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

    rows = db.execute(
        select(func.sum(Transaction.amount), func.avg(Transaction.amount))
        .where(
            Transaction.group_id.in_(group_ids),
            Transaction.is_deleted.is_(False),
            Transaction.type == "expense",
            Transaction.currency_code == currency,
            Transaction.date >= d_from,
            Transaction.date < d_to,
        )
    ).one()
    spent_sum, avg_check = rows or (0, 0)

    my_share_sum = db.execute(
        select(func.sum(TransactionShare.amount))
        .join(Transaction, Transaction.id == TransactionShare.transaction_id)
        .where(
            Transaction.group_id.in_(group_ids),
            Transaction.is_deleted.is_(False),
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


# ------------------ /dashboard/recent-groups ------------------

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
        # ВАЖНО: правильный синтаксис NULLS LAST для Postgres
        .order_by(
            nulls_last(Group.last_event_at.desc()),
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
                Transaction.is_deleted.is_(False),
                TransactionShare.user_id == current_user.id,
            )
            .group_by(Transaction.currency_code)
        ).all()
        my_balance = {ccy: f"{s or 0:.2f}" for (ccy, s) in sums}
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


# ------------------ /dashboard/top-partners ------------------

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
            Transaction.is_deleted.is_(False),
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


# ------------------ /dashboard/last-currencies ------------------

@router.get("/last-currencies", response_model=list[str])
def get_last_currencies(
    limit: int = Query(2, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    return pick_last_currencies_for_user(db, current_user.id, limit=limit)


# ------------------ /dashboard/events (UI-friendly feed) ------------------

@router.get("/events", response_model=EventsFeedOut)
def get_ui_events_feed(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    """
    UI-friendly лента событий (для фронта): возвращает готовые карточки.
    """
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
