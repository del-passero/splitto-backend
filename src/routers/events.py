# src/routers/events.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.db import get_db
from src.models.event import Event
from src.utils.telegram_dep import get_current_telegram_user
from src.schemas.event import EventOut

router = APIRouter(tags=["События"])  # ← prefix убран, остался только тег

@router.get("/", response_model=list[EventOut])
def get_events(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_telegram_user),
    limit: int = 50,
    offset: int = 0
):
    """
    Получить последние события для пользователя (сортировка по времени, пагинация)
    """
    events = db.query(Event).filter(
        (Event.actor_id == current_user.id) | (Event.target_user_id == current_user.id)
    ).order_by(Event.created_at.desc()).offset(offset).limit(limit).all()
    return events
