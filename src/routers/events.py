# src/routers/events.py
from __future__ import annotations

from typing import Annotated, Literal, Optional, Sequence

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.db import get_db
from src.models.event import Event
from src.utils.telegram_dep import get_current_telegram_user
from src.schemas.event import EventOut

router = APIRouter(tags=["События"])  # префикс задаётся в main.py: /api/events


def _types_filter_clause(t: str):
    """
    Маппинг чипов на типы событий.
    'transaction' -> type LIKE 'transaction_%'
    'update'      -> type IN (...updated...)
    'group'       -> type LIKE 'group_%'
    'user'        -> type LIKE 'member_%' OR 'user_%'
    """
    t = (t or "").strip().lower()
    if t == "transaction":
        return Event.type.like("transaction_%")
    if t == "update":
        # При желании расширишь список
        return Event.type.in_(["transaction_updated", "group_updated"])
    if t == "group":
        return Event.type.like("group_%")
    if t == "user":
        return or_(Event.type.like("member_%"), Event.type.like("user_%"))
    return None


@router.get("/", response_model=list[EventOut])
def get_events(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    types: Annotated[
        Optional[Sequence[Literal["transaction", "update", "group", "user"]]],
        Query(description="Фильтр типов для чипов. Если не передан — показываем всё."),
    ] = None,
):
    """
    Получить последние события для пользователя.
    Сохраняем существующее поведение (actor=я OR target=я), добавив безопасные фильтры.
    """
    base = select(Event).where(
        or_(
            Event.actor_id == current_user.id,
            Event.target_user_id == current_user.id,
            # Дополнительно — события из групп, где я состою (если модель событий такова)
            # or_(Event.group_id.in_(...)) — опционально, если потребуется
        )
    )

    # Фильтрация по типам (если пришло хотя бы одно значение)
    if types:
        clauses = [_types_filter_clause(t) for t in types]
        clauses = [c for c in clauses if c is not None]
        if clauses:
            base = base.where(or_(*clauses))

    rows = (
        db.execute(
            base.order_by(Event.created_at.desc()).offset(offset).limit(limit)
        )
        .scalars()
        .all()
    )

    # Возвращаем как раньше — EventOut
    return rows
