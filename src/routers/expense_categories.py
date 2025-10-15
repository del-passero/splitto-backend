# src/routers/expense_categories.py
# РОУТЕР КАТЕГОРИЙ (в стиле валют):
# - GET /api/expense-categories?parent_id=&locale=&offset=&limit=
#     • массив объектов ExpenseCategoryLocalizedOut
#     • X-Total-Count в заголовке
#     • parent_id отсутствует → возвращаем ТОЛЬКО топ-категории (parent_id IS NULL)
#     • parent_id задан → возвращаем подкатегории этого топа
# - GET /api/expense-categories/{id} → ExpenseCategoryOut (полный объект)

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from src.db import get_db
from src.models.expense_category import ExpenseCategory
from src.schemas.expense_category import ExpenseCategoryOut, ExpenseCategoryLocalizedOut
from src.utils.telegram_dep import get_current_telegram_user  # тот же guard-хедер, что и в других ручках

router = APIRouter()


def _localized_name(ec: ExpenseCategory, locale: str) -> str:
    # Берём name_i18n[locale] → иначе 'en' → иначе 'ru' → иначе любой → иначе key
    ni = getattr(ec, "name_i18n", None) or {}
    return ni.get(locale) or ni.get("en") or ni.get("ru") or next(iter(ni.values()), getattr(ec, "key", ""))


@router.get("/", response_model=List[ExpenseCategoryLocalizedOut])
def list_categories(
    response: Response,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
    parent_id: Optional[int] = Query(None, description="NULL → топ-категории; id топа → его подкатегории"),
    locale: str = Query("ru", description="Код языка ru/en/es для вычисления поля name"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    q = db.query(ExpenseCategory).filter(ExpenseCategory.is_active.is_(True))
    if parent_id is None:
        q = q.filter(ExpenseCategory.parent_id.is_(None))
    else:
        q = q.filter(ExpenseCategory.parent_id == parent_id)

    total = q.count()
    items = (
        q.order_by(ExpenseCategory.key.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    response.headers["X-Total-Count"] = str(total)
    # Маппим на локализованный ответ
    return [
        {
            "id": ec.id,
            "key": ec.key,
            "parent_id": ec.parent_id,
            "icon": ec.icon,
            "color": ec.color,
            "name": _localized_name(ec, locale),
            # поля ниже будут проигнорированы, если их нет в схеме (они Optional)
            "is_income": getattr(ec, "is_income", None),
            "is_archived": getattr(ec, "is_archived", None),
            "group_id": getattr(ec, "group_id", None),
            "created_at": getattr(ec, "created_at", None),
            "updated_at": getattr(ec, "updated_at", None),
        }
        for ec in items
    ]


@router.get("/{category_id}", response_model=ExpenseCategoryOut)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    ec = db.query(ExpenseCategory).filter(ExpenseCategory.id == category_id).first()
    if not ec:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    # КЛЮЧЕВОЕ: формируем ответ с полем name (иначе падал Pydantic)
    # Локаль как в списке по умолчанию — 'ru'
    locale = "ru"
    return {
        "id": ec.id,
        "key": ec.key,
        "parent_id": ec.parent_id,
        "icon": ec.icon,
        "color": ec.color,
        "name": _localized_name(ec, locale),
        "is_income": getattr(ec, "is_income", None),
        "is_archived": getattr(ec, "is_archived", None),
        "group_id": getattr(ec, "group_id", None),
        "created_at": getattr(ec, "created_at", None),
        "updated_at": getattr(ec, "updated_at", None),
    }
