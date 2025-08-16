# src/routers/group_categories.py
# РОУТЕР: Категории для конкретной группы (белый список)
# -----------------------------------------------------------------------------
# ЧТО ДЕЛАЕМ:
#  - GET /api/groups/{group_id}/categories
#      Возвращает список доступных категорий для группы:
#        • если для группы НЕТ записей в group_categories → разрешены ВСЕ глобальные категории;
#        • если есть записи → разрешены только они.
#      Поиск по имени (ILIKE) c JSONB (name_i18n), пагинация, сортировка по локализованному имени.
#      Требует членство в группе.
#
#  - POST /api/groups/{group_id}/categories/link    (только ВЛАДЕЛЕЦ)
#      Линкует существующую глобальную категорию к группе (добавляет в белый список).
#
#  - DELETE /api/groups/{group_id}/categories/{category_id}    (только ВЛАДЕЛЕЦ)
#      Убирает категорию из белого списка группы.
#
#  - POST /api/groups/{group_id}/categories         (создание НОВОЙ глобальной категории + линк) (ВЛАДЕЛЕЦ с PRO)
#      Создаёт новую глобальную категорию в expense_categories (PRO-пользователь),
#      и сразу линкует её к группе.
#
# ПРИМЕЧАНИЯ:
#  - Мы не удаляем/не правим существующие роуты категорий — добавляем новый «групповой слой».
#  - Все мутирующие операции запрещены для archived/deleted групп (guard в utils).
#  - Схемы:
#      • используем глобальные схемы ExpenseCategoryOut (для выдачи) и ExpenseCategoryCreate (для создания)
#      • локальная схема GroupCategoryLinkIn — см. src/schemas/group_category.py
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import List, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

# Модели
from ..models.group_category import GroupCategory
from ..models.expense_category import ExpenseCategory
from ..models.group import Group  # noqa: F401  # может использоваться в утилитах

# Схемы
from ..schemas.expense_category import ExpenseCategoryOut, ExpenseCategoryCreate
from ..schemas.group_category import GroupCategoryLinkIn

# Утилиты: общие проверки/гварды
from ..utils.groups import (
    require_membership,
    guard_mutation_for_owner,
    get_allowed_category_ids,
)

# Авторизация: текущий пользователь из Telegram WebApp
from src.utils.telegram_dep import get_current_telegram_user

from ..db import get_db

router = APIRouter(
    prefix="/groups/{group_id}/categories",  # в main.py будет /api → итоговый путь /api/groups/{group_id}/categories
)

# -----------------------------
# Вспомогательная модель ответа
# -----------------------------
from pydantic import BaseModel, Field


class GroupCategoriesListOut(BaseModel):
    """
    Ответ на GET:
    - items: список категорий (глобальные ExpenseCategoryOut)
    - total: общее количество подходящих записей (без учёта limit/offset)
    - restricted: True, если для группы есть явные записи в group_categories (т.е. белый список активен)
                  False — если белый список пуст, значит доступны все глобальные категории
    """
    items: List[ExpenseCategoryOut] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    restricted: bool = Field(..., description="Активен ли белый список категорий для этой группы")


# -----------------------
# Вспомогательные функции
# -----------------------

def _norm_locale(locale: Optional[str]) -> str:
    """ru-RU → ru, en → en; дефолт — ru (можешь сменить на 'en')."""
    return (locale or "ru").split("-")[0].lower()

def _localized_name(cat: ExpenseCategory, loc: str) -> str:
    """Локализованное имя из JSONB с фолбэком."""
    try:
        d: Dict[str, str] = (cat.name_i18n or {})  # type: ignore
        return d.get(loc) or d.get("en") or cat.key
    except Exception:
        return cat.key

def _slugify_key(s: str) -> str:
    """Очень простой slug → snake_case ascii-ключ."""
    import re
    s = s.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s\-]+", "_", s)
    return s[:64] if s else "category"


# -------------
# GET /… (list)
# -------------
@router.get("", response_model=GroupCategoriesListOut, summary="Список категорий, доступных этой группе")
def list_group_categories(
    group_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
    q: Optional[str] = Query(None, description="Поиск по имени категории (ILIKE)"),
    limit: int = Query(100, ge=1, le=500, description="Лимит записей"),
    offset: int = Query(0, ge=0, description="Смещение"),
    locale: Optional[str] = Query(None, description="Локаль для имён (например, ru, en, es). По умолчанию ru."),
):
    """
    Возвращает доступные этой группе категории.
    Требует членство пользователя в группе.
    Поведение:
      - Если white-list (group_categories) для группы пуст → отдаём все активные глобальные категории.
      - Если white-list непуст → отдаём только категории из него.
    """
    # 1) Проверяем членство в группе.
    require_membership(db, group_id, current_user.id)

    # 2) Выясняем, есть ли явные ограничения по категориям для этой группы.
    allowed_ids = get_allowed_category_ids(db, group_id)
    restricted = allowed_ids is not None  # True — есть записи в group_categories

    # 3) Базовый запрос к ExpenseCategory
    base = select(ExpenseCategory).where(ExpenseCategory.is_active.is_(True))
    if restricted:
        if not allowed_ids:
            return GroupCategoriesListOut(items=[], total=0, restricted=True)
        base = base.where(ExpenseCategory.id.in_(sorted(allowed_ids)))

    # Поиск по имени: JSONB name_i18n ->> loc / 'en', + key
    loc = _norm_locale(locale)
    if q:
        pattern = f"%{q.strip()}%"
        name_loc = ExpenseCategory.name_i18n[loc].astext  # ->> loc
        name_en = ExpenseCategory.name_i18n["en"].astext
        base = base.where(
            or_(
                name_loc.ilike(pattern),
                name_en.ilike(pattern),
                ExpenseCategory.key.ilike(pattern),
            )
        )

    # total ДО пагинации
    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)

    # Сортировка по локализованному имени (COALESCE: loc → en → key)
    name_order = func.coalesce(
        ExpenseCategory.name_i18n[loc].astext,
        ExpenseCategory.name_i18n["en"].astext,
        ExpenseCategory.key,
    )

    stmt = base.order_by(name_order.asc()).limit(limit).offset(offset)
    rows: List[ExpenseCategory] = list(db.scalars(stmt).all())

    # ORM → схема с подстановкой локализованного имени
    items: List[ExpenseCategoryOut] = []
    for r in rows:
        payload = {
            "id": r.id,
            "key": r.key,
            "name": _localized_name(r, loc),
            "icon": r.icon,
            "color": r.color,
            "parent_id": r.parent_id,
            "is_active": r.is_active,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        # Если в ExpenseCategoryOut поле name_i18n есть — тоже положим:
        if hasattr(ExpenseCategoryOut, "model_fields") and "name_i18n" in getattr(ExpenseCategoryOut, "model_fields"):
            payload["name_i18n"] = r.name_i18n
        items.append(ExpenseCategoryOut.model_validate(payload))

    return GroupCategoriesListOut(items=items, total=total, restricted=restricted)


# -------------------
# POST /…/link (owner)
# -------------------
@router.post("/link", status_code=status.HTTP_204_NO_CONTENT, summary="Линкует существующую категорию к группе (owner)")
def link_category_to_group(
    group_id: int,
    payload: GroupCategoryLinkIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    """
    Добавляет запись в group_categories (белый список):
      - доступно ТОЛЬКО владельцу группы,
      - запрещено для archived/deleted групп.
    Идемпотентность: если запись уже есть — просто возвращаем 204.
    """
    # 1) Гарды владельца и статуса группы (not archived, not deleted)
    group = guard_mutation_for_owner(db, group_id, current_user.id)

    # 2) Проверяем существование глобальной категории
    cat = db.scalar(select(ExpenseCategory).where(ExpenseCategory.id == payload.category_id))
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    # 3) Проверяем наличие связки (group_id, category_id)
    exists = db.scalar(
        select(func.count()).select_from(GroupCategory).where(
            GroupCategory.group_id == group_id,
            GroupCategory.category_id == payload.category_id,
        )
    )
    if exists:
        return  # идемпотентно

    # 4) Создаём связь
    gc = GroupCategory(
        group_id=group_id,
        category_id=payload.category_id,
        created_by=current_user.id,
    )
    db.add(gc)
    db.commit()
    # 204 No Content


# -----------------------
# DELETE /…/{id} (owner)
# -----------------------
@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Убирает категорию из белого списка (owner)")
def unlink_category_from_group(
    group_id: int,
    category_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    """
    Удаляет запись (group_id, category_id) из group_categories:
      - доступно ТОЛЬКО владельцу группы,
      - запрещено для archived/deleted групп,
      - идемпотентно: если записи нет — возвращаем 204.
    """
    # 1) Гарды владельца и статуса
    group = guard_mutation_for_owner(db, group_id, current_user.id)

    # 2) Найти и удалить связь, если есть
    row = db.scalar(
        select(GroupCategory).where(
            GroupCategory.group_id == group_id,
            GroupCategory.category_id == category_id,
        )
    )
    if not row:
        return
    db.delete(row)
    db.commit()
    # 204 No Content


# -------------------------------------------------
# POST /…  (create global category + link) (owner+PRO)
# -------------------------------------------------
@router.post(
    "",
    response_model=ExpenseCategoryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создаёт НОВУЮ глобальную категорию и линкует к группе (owner + PRO)",
)
def create_and_link_category(
    group_id: int,
    payload: ExpenseCategoryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
    locale: Optional[str] = Query(None, description="Локаль для имени по умолчанию при создании (если дано только name)"),
):
    """
    Создаёт новую запись в глобальной таблице expense_categories (ТОЛЬКО PRO-пользователь),
    после чего добавляет её в белый список этой группы.
    Доступно ТОЛЬКО владельцу группы.
    """
    # 1) Гарды владельца/статуса
    group = guard_mutation_for_owner(db, group_id, current_user.id)

    # 2) Проверка PRO-статуса
    if not bool(getattr(current_user, "is_pro", False)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only PRO users can create new categories")

    # 3) Разбор входных данных (гибко к схеме)
    # Ожидаемые поля в ExpenseCategoryCreate (варианты):
    #   key: str | None
    #   name: str | None
    #   name_i18n: dict[str, str] | None
    #   parent_id: int | None
    #   icon: str | None
    #   color: str | None
    #   is_active: bool | None
    in_key = getattr(payload, "key", None)
    in_name = getattr(payload, "name", None)
    in_name_i18n = getattr(payload, "name_i18n", None)
    parent_id = getattr(payload, "parent_id", None)
    icon = getattr(payload, "icon", None)
    color = getattr(payload, "color", None)
    is_active = getattr(payload, "is_active", True)

    # Сформируем key
    if not in_key:
        if in_name:
            in_key = _slugify_key(in_name)
        else:
            raise HTTPException(status_code=400, detail="Either 'key' or 'name' must be provided")

    # Проверка уникальности key
    existed = db.scalar(select(func.count()).select_from(ExpenseCategory).where(ExpenseCategory.key == in_key))
    if existed:
        raise HTTPException(status_code=409, detail="Category key already exists")

    # Сформируем name_i18n
    loc = _norm_locale(locale)
    if in_name_i18n and isinstance(in_name_i18n, dict) and in_name_i18n:
        name_i18n = dict(in_name_i18n)
    else:
        # Если пришло только 'name' — положим в текущую локаль и/или en
        if not in_name:
            raise HTTPException(status_code=400, detail="Provide 'name' or 'name_i18n'")
        name_i18n = {loc: in_name}
        # чтобы фронт на en тоже видел
        if "en" not in name_i18n:
            name_i18n["en"] = in_name

    # Валидация подкатегории: если есть parent_id — проверим его существование
    if parent_id is not None:
        parent = db.scalar(select(ExpenseCategory).where(ExpenseCategory.id == parent_id))
        if not parent:
            raise HTTPException(status_code=404, detail="Parent category not found")

    # 4) Создаём глобальную категорию
    new_cat = ExpenseCategory(
        key=in_key,
        parent_id=parent_id,
        icon=icon,
        color=color,
        name_i18n=name_i18n,  # JSONB
        is_active=bool(is_active),
    )
    db.add(new_cat)
    db.flush()  # получить id до коммита

    # 5) Линкуем к группе
    link = GroupCategory(
        group_id=group_id,
        category_id=new_cat.id,
        created_by=current_user.id,
    )
    db.add(link)
    db.commit()
    db.refresh(new_cat)

    # 6) Ответ с локализованным именем
    out_payload = {
        "id": new_cat.id,
        "key": new_cat.key,
        "name": _localized_name(new_cat, loc),
        "icon": new_cat.icon,
        "color": new_cat.color,
        "parent_id": new_cat.parent_id,
        "is_active": new_cat.is_active,
        "created_at": new_cat.created_at,
        "updated_at": new_cat.updated_at,
    }
    if hasattr(ExpenseCategoryOut, "model_fields") and "name_i18n" in getattr(ExpenseCategoryOut, "model_fields"):
        out_payload["name_i18n"] = new_cat.name_i18n

    return ExpenseCategoryOut.model_validate(out_payload)
