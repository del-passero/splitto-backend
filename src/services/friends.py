# src/services/friends.py
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session

from src.models.friend import Friend
from src.services.events import log_event, FRIENDSHIP_CREATED

def _sorted_pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)

def ensure_friendship(
    db: Session,
    inviter_id: int,        # кто добавляет в группу (Саша)
    invitee_id: int,        # кого добавили (Вася)
    group_id: int | None,   # укажи group_id, если событие должны видеть все в группе
) -> Friend:
    """
    Гарантирует дружбу между inviter_id и invitee_id.
    Если её не было — создаёт запись и логирует FRIENDSHIP_CREATED (идемпотентно).
    Если уже есть — ничего не пишет.
    """
    a, b = _sorted_pair(inviter_id, invitee_id)

    link = (
        db.query(Friend)
        .filter(Friend.user_min == a, Friend.user_max == b)
        .first()
    )
    if link:
        return link

    now = datetime.utcnow()
    link = Friend(
        user_min=a, user_max=b,
        hidden_by_min=False, hidden_by_max=False,
        created_at=now, updated_at=now,
        # legacy-поля на переходный период:
        user_id=a, friend_id=b, hidden=False,
    )
    db.add(link)
    db.flush()  # остаёмся в общей транзакции

    log_event(
        db,
        type=FRIENDSHIP_CREATED,
        actor_id=inviter_id,
        target_user_id=invitee_id,
        group_id=group_id,  # None -> событие увидят только Саша и Вася; иначе — вся группа
        idempotency_key=f"friendship_created:{a}:{b}",
    )

    return link
