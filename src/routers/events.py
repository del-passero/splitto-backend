# src/routers/events.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from src.db import get_db
from src.models.event import Event
from src.models.group_member import GroupMember
from src.schemas.event import EventOut  # у тебя уже есть схема EventOut
from src.utils.telegram_dep import get_current_telegram_user
from src.models.user import User

router = APIRouter(prefix="/events", tags=["События"])

# -------- фильтрация по "чипам" (types[]) --------
# Поддержим прежние чипы + базовые префиксы.
# Можно расширять без миграций — это просто условия в запросе.
def _apply_types_filter(q, types: Optional[List[str]]):
    if not types:
        return q

    # Нормализуем к нижнему регистру
    tset = {t.lower().strip() for t in types if t and t.strip()}
    if not tset:
        return q

    clauses = []
    # Группы
    if "group" in tset:
        clauses.append(Event.type.like("group_%"))
    # Пользователи/участники (дружба, участники групп)
    if "user" in tset:
        clauses.append(Event.type.like("user_%"))
        clauses.append(Event.type.like("member_%"))
        clauses.append(Event.type.like("friendship_%"))
        clauses.append(Event.type.in_(["friend_added", "friend_hidden", "friend_unhidden", "invite_registered"]))  # старые типы, если где-то остались
    # Транзакции (все)
    if "transaction" in tset:
        clauses.append(Event.type.like("transaction_%"))
    # "update" — всё, что явно апдейты
    if "update" in tset:
        clauses.append(Event.type.in_(["transaction_updated", "group_renamed", "group_avatar_changed"]))

    # Если передали полноценные типы (точные совпадения), тоже поддержим
    other_exact = [t for t in tset if t not in {"group", "user", "member", "transaction", "update"}]
    if other_exact:
        clauses.append(Event.type.in_(other_exact))

    # Соединяем OR, но оборачиваем в один AND с исходным запросом
    if clauses:
        q = q.where(or_(*clauses))
    return q


@router.get("/", response_model=List[EventOut])
def list_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    # пагинация
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    # фильтры
    types: Optional[List[str]] = Query(None, description="Фильтры-чипы или точные типы"),
    group_id: Optional[int] = Query(None, description="Вернуть события только по этой группе"),
    since: Optional[datetime] = Query(None, description="created_at >= since"),
    before: Optional[datetime] = Query(None, description="created_at < before"),
):
    """
    Возвращает события, видимые текущему пользователю:
      - actor == me или target == me
      - ИЛИ событие связано с группой, где я сейчас состою (GroupMember.deleted_at IS NULL)
    Поддерживает пагинацию и фильтры.
    """
    me = current_user

    base = select(Event).where(
        or_(
            Event.actor_id == me.id,
            Event.target_user_id == me.id,
            and_(
                Event.group_id.isnot(None),
                exists(
                    select(1).where(
                        and_(
                            GroupMember.group_id == Event.group_id,
                            GroupMember.user_id == me.id,
                            GroupMember.deleted_at.is_(None),
                        )
                    )
                ),
            ),
        )
    )

    if group_id is not None:
        base = base.where(Event.group_id == group_id)

    if since is not None:
        base = base.where(Event.created_at >= since)

    if before is not None:
        base = base.where(Event.created_at < before)

    base = _apply_types_filter(base, types)

    base = base.order_by(Event.created_at.desc()).offset(offset).limit(limit)
    rows = db.execute(base).scalars().all()
    return rows
