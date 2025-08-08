# src/routers/group_categories.py
# РОУТЕР: Категории для конкретной группы (белый список)
# -----------------------------------------------------------------------------
# ЧТО ДЕЛАЕМ:
#  - GET /api/groups/{group_id}/categories
#      Возвращает список доступных категорий для группы:
#        • если для группы НЕТ записей в group_categories → считаем, что разрешены ВСЕ глобальные категории;
#        • если есть записи → разрешены только они.
#      Поиск по имени (ILIKE), пагинация. Требует членство в группе.
#
#  - POST /api/groups/{group_id}/categories/link    (только ВЛАДЕЛЕЦ)
#      Линкует существующую глобальную категорию к группе (добавляет в белый список).
#
#  - DELETE /api/groups/{group_id}/categories/{category_id}    (только ВЛАДЕЛЕЦ)
#      Убирает категорию из белого списка группы.
#
#  - POST /api/groups/{group_id}/categories         (создание НОВОЙ глобальной категории + линк) (ВЛАДЕЛЕЦ с PRO)
#      Создаёт новую глобальную категорию в expense_categories (доступно только PRO-пользователю),
#      и сразу линкует её к группе.
#
# ПРИМЕЧАНИЯ:
#  - Мы не удаляем/не правим существующие роуты категорий — добавляем новый «групповой слой».
#  - Все мутирующие операции запрещены для archived/deleted групп (guard в utils).
#  - Схемы:
#      • используем твою глобальную схему ExpenseCategoryOut (для выдачи)
#      • и ExpenseCategoryCreate (для создания новой категории)
#      • а также локальную схему GroupCategoryLinkIn (ID категории для link) — см. src/schemas/group_category.py
#
# ЗАВИСИМОСТИ:
#  - telegram_dep.get_current_telegram_user — текущий пользователь (Telegram WebApp auth)
#  - db.get_db — сессия БД
#  - utils.groups — проверки (членство/владелец/архив/удаление), список разрешённых категорий
#
# ВАЖНО:
#  - Миграции под таблицу group_categories мы сделаем ПОЗЖЕ общим пакетом (как договорились).
#  - До миграций этот код не запускаем.

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

# Модели
from ..models.group_category import GroupCategory
from ..models.expense_category import ExpenseCategory
from ..models.group import Group

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
):
    """
    Возвращает доступные этой группе категории.
    Требует членство пользователя в группе.
    Поведение:
      - Если white-list (group_categories) для группы пуст → отдаём все глобальные категории.
      - Если white-list непуст → отдаём только категории из него.
    """
    # 1) Проверяем, что пользователь — участник группы (и что группа существует и не soft-deleted).
    require_membership(db, group_id, current_user.id)

    # 2) Выясняем, есть ли явные ограничения по категориям для этой группы.
    allowed_ids = get_allowed_category_ids(db, group_id)
    restricted = allowed_ids is not None  # True — есть записи в group_categories

    # 3) Строим запрос к таблице ExpenseCategory
    stmt = select(ExpenseCategory)
    if restricted:
        # Белый список активен → фильтруем только по разрешённым
        if not allowed_ids:
            # Теоретически сюда попасть нельзя (allowed_ids == set() происходит только при некорректных данных),
            # но на всякий случай отдаём пустой список
            return GroupCategoriesListOut(items=[], total=0, restricted=True)
        stmt = stmt.where(ExpenseCategory.id.in_(sorted(allowed_ids)))

    # Поиск по имени (ILIKE)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(ExpenseCategory.name.ilike(pattern))

    # Подсчёт total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    # Пагинация и сортировка (по алфавиту)
    stmt = stmt.order_by(ExpenseCategory.name.asc()).limit(limit).offset(offset)
    rows = list(db.scalars(stmt).all())

    # Сериализуем ORM → Pydantic через from_attributes
    items = [ExpenseCategoryOut.model_validate(r, from_attributes=True) for r in rows]

    return GroupCategoriesListOut(items=items, total=int(total), restricted=restricted)


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

    # 2) Проверяем, что такая глобальная категория существует
    cat = db.scalar(select(ExpenseCategory).where(ExpenseCategory.id == payload.category_id))
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    # 3) Проверяем, нет ли уже такой связки (group_id, category_id)
    exists = db.scalar(
        select(func.count())
        .select_from(GroupCategory)
        .where(
            GroupCategory.group_id == group_id,
            GroupCategory.category_id == payload.category_id,
        )
    )
    if exists:
        # уже связано — считаем операцию успешной и идемпотентной
        return

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
        return  # идемпотентно
    db.delete(row)
    db.commit()
    # 204 No Content


# -------------------------------------------------
# POST /…  (create global category + link) (owner+PRO)
# -------------------------------------------------
@router.post("", response_model=ExpenseCategoryOut, status_code=status.HTTP_201_CREATED,
             summary="Создаёт НОВУЮ глобальную категорию и линкует к группе (owner + PRO)")
def create_and_link_category(
    group_id: int,
    payload: ExpenseCategoryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    """
    Создаёт новую запись в глобальной таблице expense_categories (ТОЛЬКО PRO-пользователь),
    после чего добавляет её в белый список этой группы.
    Доступно ТОЛЬКО владельцу группы (с учётом нашей политики «владелец — все права, кроме удаления группы»).
    """
    # 1) Гарды владельца/статуса
    group = guard_mutation_for_owner(db, group_id, current_user.id)

    # 2) Проверка PRO-статуса
    if not bool(getattr(current_user, "is_pro", False)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only PRO users can create new categories")

    # 3) Создаём глобальную категорию (если такая 'name' уже есть — можно либо запретить, либо разрешить дубликаты).
    #    Здесь мы НЕ запрещаем одинаковые имена (это может быть осознанная политика),
    #    но при желании можно сделать проверку уникальности имени.
    new_cat = ExpenseCategory(
        name=payload.name.strip(),
        icon=(payload.icon or None),
    )
    db.add(new_cat)
    db.flush()  # чтобы получить new_cat.id до коммита

    # 4) Линкуем к группе (идемпотентность не нужна — запись точно новая)
    link = GroupCategory(
        group_id=group_id,
        category_id=new_cat.id,
        created_by=current_user.id,
    )
    db.add(link)
    db.commit()
    db.refresh(new_cat)

    # 5) Возвращаем созданную категорию (в формате ExpenseCategoryOut)
    return ExpenseCategoryOut.model_validate(new_cat, from_attributes=True)
