# src/routers/currencies.py
# РОУТЕР СПРАВОЧНИКА ВАЛЮТ
# -----------------------------------------------------------------------------
# Что делает этот файл:
#  - Возвращает список валют с локализованными названиями (для "списка выбора" на фронте).
#  - Возвращает "популярные" валюты (для шапки списка).
#  - Возвращает конкретную валюту по коду.
#
# Ключевые детали:
#  - Локализация имён берётся из JSONB-поля Currency.name_i18n (ключи "ru", "en", ...).
#  - Локаль берём из query (?locale=ru) ИЛИ из заголовка Accept-Language (берём первую).
#  - Поиск работает по коду (USD) и по локализованному названию (через ILIKE).
#  - По умолчанию отдаём только активные валюты (is_active=true); можно отключить.
#  - Результаты отсортированы по локализованному имени (чтобы список выглядел аккуратно).
#
# Зависимости:
#  - Модель Currency (src/models/currency.py)
#  - Схемы CurrencyLocalizedOut (src/schemas/currency.py)
#
# ВАЖНО: миграции и сидинг таблицы currencies мы сделаем ПОЗЖЕ (по нашему плану).
# Пока готовим код роутера; до миграций запускать не нужно.

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query, Request, Response, HTTPException
from starlette import status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

# Модели и схемы
from ..models.currency import Currency
from ..schemas.currency import CurrencyLocalizedOut

# Зависимость получения сессии БД
from ..db import get_db

router = APIRouter(
    prefix="/currencies",   # в main.py будет подключено под /api → итого: /api/currencies
)


# =========================
# УТИЛИТЫ ДЛЯ ЛОКАЛИЗАЦИИ
# =========================

_ALLOWED_LOCALES = {"ru", "en", "es"}  # при желании расширим; "en" используем как безопасный fallback
_DEFAULT_LOCALE = "en"


def _pick_locale(request: Request, locale_param: Optional[str]) -> str:
    """
    Возвращает "нормализованную" локаль для выдачи.
    Приоритет:
      1) query-параметр ?locale=ru
      2) заголовок Accept-Language: берём первый язык до запятой/точки с запятой
      3) _DEFAULT_LOCALE ("en")
    Разрешённые локали — из _ALLOWED_LOCALES; иначе fallback на "en".
    """
    # 1) query-параметр
    if locale_param:
        cand = locale_param.lower()
        return cand if cand in _ALLOWED_LOCALES else _DEFAULT_LOCALE

    # 2) Accept-Language
    al = (request.headers.get("accept-language") or "").strip()
    if al:
        # Берём первую "часть" до запятой, затем до ';'
        first = al.split(",")[0].split(";")[0].strip().lower()
        # Часто Accept-Language приходит "ru-RU" → берём подстроку до '-'
        first = first.split("-")[0]
        if first in _ALLOWED_LOCALES:
            return first

    # 3) Fallback
    return _DEFAULT_LOCALE


def _localized_name_expr(locale: str):
    """
    Возвращает SQLAlchemy-выражение (для PostgreSQL JSONB), которое берёт:
      COALESCE(name_i18n[locale]::text, name_i18n['en']::text)
    Это позволяет:
      - сортировать по локализованному имени,
      - фильтровать ILIKE по локализованному имени (поиск).
    """
    # .astext → привести JSON-значение к тексту (PostgreSQL JSONB → TEXT)
    return func.coalesce(
        Currency.name_i18n[locale].astext,
        Currency.name_i18n["en"].astext,
    )


def _to_localized_dto(row: Currency, locale: str) -> CurrencyLocalizedOut:
    """
    Преобразует ORM-объект Currency в DTO с локализованным полем name.
    Мы НЕ тащим весь name_i18n на фронт, а выбираем одно значение по локали
    (fall back на "en").
    """
    name_i18n = row.name_i18n or {}
    # Пробуем локаль, затем fallback на 'en', если и там нет — на code
    name = name_i18n.get(locale) or name_i18n.get("en") or row.code
    return CurrencyLocalizedOut(
        code=row.code,
        numeric_code=int(row.numeric_code),
        name=name,
        symbol=row.symbol,
        decimals=int(row.decimals),
        flag_emoji=row.flag_emoji,
        is_popular=bool(row.is_popular),
    )


# =========================
# МОДЕЛИ ОТВЕТОВ (ДЛЯ СХЕМЫ)
# =========================

# Чтобы не править сейчас общий пакет схем, определим локальную обёртку для списка.
# Это снимает необходимость добавлять новый файл schemas/CurrencyListOut прямо сейчас.
from pydantic import BaseModel, Field


class CurrencyListResponse(BaseModel):
    """
    Ответ на GET /currencies:
      - items: массив локализованных валют
      - total: количество записей БЕЗ учёта limit/offset (удобно для пагинации/инфо).
    """
    items: List[CurrencyLocalizedOut] = Field(default_factory=list)
    total: int = Field(..., ge=0)


# =========================
# РОУТЫ
# =========================

@router.get(
    "",
    response_model=CurrencyListResponse,
    summary="Список валют (с локализованными названиями)",
)
def list_currencies(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Поиск по коду и локализованному имени (ILIKE)"),
    locale: Optional[str] = Query(None, description="Локаль для названий (ru|en|es)"),
    limit: int = Query(100, ge=1, le=500, description="Лимит записей"),
    offset: int = Query(0, ge=0, description="Смещение"),
    only_active: bool = Query(True, description="Отдавать только активные валюты (is_active=true)"),
):
    """
    Возвращает список валют, отсортированный по локализованному имени.
    По умолчанию — только активные. Поиск работает по коду и локализованному имени.
    """
    loc = _pick_locale(request, locale)
    name_expr = _localized_name_expr(loc)

    # Базовый запрос (с фильтром активности при необходимости)
    stmt = select(Currency)
    if only_active:
        stmt = stmt.where(Currency.is_active.is_(True))

    # Фильтр поиска (по коду и локализованному имени)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            (Currency.code.ilike(pattern)) | (name_expr.ilike(pattern))
        )

    # Подсчёт total (до limit/offset)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    # Запрос самих данных
    stmt = stmt.order_by(name_expr.asc()).limit(limit).offset(offset)
    rows = list(db.scalars(stmt).all())

    # Сериализация в локализованные DTO
    items = [_to_localized_dto(r, loc) for r in rows]

    # Кэш: справочник статичен — отдаём долго живущие заголовки (можно менять по вкусу)
    # Если это поиск (q задан), можно поставить меньший max-age, но в целом справочник редкий.
    response.headers["Cache-Control"] = "public, max-age=86400"

    return CurrencyListResponse(items=items, total=int(total))


@router.get(
    "/popular",
    response_model=List[CurrencyLocalizedOut],
    summary="Популярные валюты (для шапки списка)",
)
def list_popular_currencies(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    locale: Optional[str] = Query(None, description="Локаль для названий (ru|en|es)"),
    only_active: bool = Query(True, description="Отдавать только активные валюты"),
    limit: int = Query(20, ge=1, le=100, description="Максимум популярных валют"),
):
    """
    Возвращает «популярные» валюты (is_popular=true), отсортированные по локализованному имени.
    Эта выдача используется для верхнего блока "Популярные" в селекторе.
    """
    loc = _pick_locale(request, locale)
    name_expr = _localized_name_expr(loc)

    stmt = select(Currency).where(Currency.is_popular.is_(True))
    if only_active:
        stmt = stmt.where(Currency.is_active.is_(True))

    stmt = stmt.order_by(name_expr.asc()).limit(limit)
    rows = list(db.scalars(stmt).all())
    items = [_to_localized_dto(r, loc) for r in rows]

    # Кэшируем сильнее: популярные редко меняются
    response.headers["Cache-Control"] = "public, max-age=86400"

    return items


@router.get(
    "/{code}",
    response_model=CurrencyLocalizedOut,
    summary="Валюта по коду (локализованная)",
)
def get_currency_by_code(
    code: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    locale: Optional[str] = Query(None, description="Локаль для названия (ru|en|es)"),
    only_active: bool = Query(True, description="Только активные валюты"),
):
    """
    Возвращает валюту по коду (например, /USD), с локализованным именем.
    """
    loc = _pick_locale(request, locale)
    norm_code = (code or "").upper().strip()

    stmt = select(Currency).where(Currency.code == norm_code)
    if only_active:
        stmt = stmt.where(Currency.is_active.is_(True))

    row = db.scalar(stmt)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Currency not found")

    dto = _to_localized_dto(row, loc)

    # Кэшируем карточку валюты
    response.headers["Cache-Control"] = "public, max-age=86400"

    return dto
