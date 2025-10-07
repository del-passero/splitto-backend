# src/schemas/dashboard.py
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel
from src.schemas.user import UserOut


# --------- Balance (верхняя полоса) ---------
class DashboardBalanceOut(BaseModel):
    i_owe: dict[str, str]            # {"USD":"-50.00","RUB":"-2300.00"}
    they_owe_me: dict[str, str]      # {"USD":"+125.00"}
    last_currencies: list[str]       # ["RUB","USD"]


# --------- Activity (бакеты) ---------
class ActivityBucketOut(BaseModel):
    date: date
    count: int


class DashboardActivityOut(BaseModel):
    period: Literal["week", "month", "year"]
    buckets: list[ActivityBucketOut]


# --------- Топ-категории ---------
class TopCategoryItemOut(BaseModel):
    category_id: int
    name: Optional[str] = None
    sum: str
    currency: str
    icon: Optional[str] = None
    color: Optional[str] = None


class TopCategoriesOut(BaseModel):
    period: Literal["week", "month", "year"]
    items: list[TopCategoryItemOut]
    total: int


# --------- Сводка (3 столбца) ---------
class DashboardSummaryOut(BaseModel):
    period: Literal["day", "week", "month", "year"]
    currency: str
    spent: str
    avg_check: str
    my_share: str


# --------- Последние активные группы (узкая карточка) ---------
class RecentGroupCardOut(BaseModel):
    id: int
    name: str
    avatar_url: Optional[str] = None
    my_balance_by_currency: dict[str, str]
    last_event_at: Optional[datetime] = None


# --------- Топ партнёров (карусель) ---------
class TopPartnerItemOut(BaseModel):
    user: UserOut
    joint_expense_count: int
    period: Literal["week", "month", "year"]


# --------- Лента (UI-ready) ---------
class EventFeedItemOut(BaseModel):
    id: int
    type: str
    created_at: datetime
    title: str
    subtitle: Optional[str] = None
    icon: str
    entity: dict


class EventsFeedOut(BaseModel):
    items: list[EventFeedItemOut]
