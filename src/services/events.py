# src/services/events.py
from __future__ import annotations
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.models.event import Event

# Рекомендуемые константы типов (используй в роутерах)
FRIENDSHIP_CREATED = "friendship_created"
FRIENDSHIP_REMOVED = "friendship_removed"

GROUP_CREATED = "group_created"
GROUP_RENAMED = "group_renamed"
GROUP_AVATAR_CHANGED = "group_avatar_changed"
GROUP_DELETED = "group_deleted"
GROUP_ARCHIVED = "group_archived"
GROUP_UNARCHIVED = "group_unarchived"

MEMBER_ADDED = "member_added"
MEMBER_REMOVED = "member_removed"
MEMBER_LEFT = "member_left"

TRANSACTION_CREATED = "transaction_created"
TRANSACTION_UPDATED = "transaction_updated"
TRANSACTION_RECEIPT_ADDED = "transaction_receipt_added"
TRANSACTION_RECEIPT_REPLACED = "transaction_receipt_replaced"
TRANSACTION_RECEIPT_REMOVED = "transaction_receipt_removed"


def log_event(
    db: Session,
    *,
    type: str,
    actor_id: int,
    group_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    transaction_id: Optional[int] = None,
    data: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> Event:
    """
    Единая точка записи событий. Вызывается в той же транзакции, что и бизнес-операция.
    Не делает commit. Если задан idempotency_key — обеспечиваем идемпотентность без IntegrityError.
    """
    payload = {
        "type": type,
        "actor_id": actor_id,
        "group_id": group_id,
        "target_user_id": target_user_id,
        "transaction_id": transaction_id,
        "data": (data or {}),
        "idempotency_key": idempotency_key,
    }

    if idempotency_key:
        # PostgreSQL: ON CONFLICT DO NOTHING по уникальному ключу idempotency_key
        stmt = (
            pg_insert(Event.__table__)
            .values(**payload)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(Event.id)
        )
        res = db.execute(stmt)
        inserted_id = res.scalar_one_or_none()
        if inserted_id is not None:
            # подхватим ORM-объект для удобства
            return db.query(Event).filter(Event.id == inserted_id).first()  # type: ignore
        # конфликт: запись уже есть — вернём существующую
        existing = db.query(Event).filter(Event.idempotency_key == idempotency_key).first()
        if existing:
            return existing
        # крайне маловероятно, но на всякий случай создадим ORM-объект (не должно сюда доходить)
        ev = Event(**payload)
        db.add(ev)
        return ev

    # без идемпотентности — обычная ORM-вставка
    ev = Event(**payload)
    db.add(ev)
    return ev


def make_tx_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """
    Универсальный дифф для транзакций (под TRANSACTION_UPDATED).
    Сравнивает ключи и собирает { changed: [...], diff: {field:{old,new}} }.
    """
    changed = []
    diff: Dict[str, Any] = {}
    keys = set(before.keys()) | set(after.keys())
    for k in keys:
        if before.get(k) != after.get(k):
            changed.append(k)
            diff[k] = {"old": before.get(k), "new": after.get(k)}
    return {"changed": changed, "diff": diff}


def safe_tx_payload(tx: Any) -> Dict[str, Any]:
    """
    Безопасно собирает полезный payload для событий транзакций.
    Не падает, если каких-то полей нет; приводит числа к строкам.
    """
    def _get(obj: Any, name: str) -> Any:
        return getattr(obj, name, None)

    def _str_num(v: Any) -> Optional[str]:
        if v is None:
            return None
        try:
            return str(v)
        except Exception:
            return None

    return {
        "transaction_id": _get(tx, "id"),
        "group_id": _get(tx, "group_id"),
        "kind": _get(tx, "type") or _get(tx, "tx_type"),
        "amount": _str_num(_get(tx, "amount")),
        "currency": _get(tx, "currency_code"),
        "title": _get(tx, "title"),
        "payer_id": _get(tx, "paid_by") or _get(tx, "created_by"),
        "date": _str_num(_get(tx, "date")),
    }
