# src/routers/transactions.py
# -----------------------------------------------------------------------------
# РОУТЕР: Транзакции (+ привязка/удаление чека с нормализацией URL)
# -----------------------------------------------------------------------------
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Dict, Iterable, Set
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from starlette import status
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import select, func

from src.db import get_db
from src.models.transaction import Transaction
from src.models.transaction_share import TransactionShare
from src.models.currency import Currency
from src.models.user import User
from src.models.group import Group
from src.models.group_member import GroupMember
from src.schemas.transaction import TransactionCreate, TransactionUpdate, TransactionOut
from src.schemas.user import UserOut

from src.utils.telegram_dep import get_current_telegram_user
from src.utils.groups import (
    require_membership,
    guard_mutation_for_member,
    get_group_member_ids,
    get_allowed_category_ids,
    is_category_allowed,
    ensure_group_active,
)

from pydantic import BaseModel, constr

# === Общие медиа-утилиты ======================================================
from src.utils.media import (
    to_abs_media_url,
    url_to_media_local_path,
    delete_if_local,
)

# === Логи событий =============================================================
from src.services.events import (
    log_event,
    make_tx_diff,
    TRANSACTION_CREATED,
    TRANSACTION_UPDATED,
    TRANSACTION_RECEIPT_ADDED,
    TRANSACTION_RECEIPT_REPLACED,
    TRANSACTION_RECEIPT_REMOVED,
)

router = APIRouter()

# ===== Вспомогательные (квантизация) =========================================

def _quant_for_decimals(decimals: int) -> Decimal:
    if decimals <= 0:
        return Decimal("1")
    return Decimal("1").scaleb(-decimals)

def q(x: Decimal, decimals: int) -> Decimal:
    return x.quantize(_quant_for_decimals(decimals), rounding=ROUND_HALF_UP)

def get_currency_decimals(db: Session, code: str) -> int:
    cur = db.scalar(select(Currency).where(Currency.code == code))
    if not cur:
        raise HTTPException(status_code=404, detail="Currency not found")
    return int(cur.decimals or 2)

# ===== Вспомогательные: связанные пользователи/валидаторы =====================

def _involved_user_ids(tx: Transaction) -> Set[int]:
    ids: Set[int] = set()
    if tx.type == "expense":
        if tx.paid_by is not None:
            ids.add(int(tx.paid_by))
        for s in (tx.shares or []):
            if s.user_id is not None:
                ids.add(int(s.user_id))
    elif tx.type == "transfer":
        if tx.transfer_from is not None:
            ids.add(int(tx.transfer_from))
        for uid in (tx.transfer_to or []):
            if uid is not None:
                ids.add(int(uid))
    return ids

def _attach_related_users(db: Session, tx: Transaction) -> None:
    ids = _involved_user_ids(tx)
    if not ids:
        setattr(tx, "related_users", [])
        return
    users = db.query(User).filter(User.id.in_(ids)).all()
    users_sorted = sorted(users, key=lambda u: u.id or 0)
    setattr(tx, "related_users", users_sorted)

def _inactive_participants(db: Session, group_id: int, tx: Transaction) -> List[User]:
    active_member_ids = set(get_group_member_ids(db, group_id))
    involved = _involved_user_ids(tx)
    missing_ids = [uid for uid in involved if uid not in active_member_ids]
    if not missing_ids:
        return []
    users = db.query(User).filter(User.id.in_(missing_ids)).all()
    return sorted(users, key=lambda u: u.id or 0)

def _require_membership_incl_deleted_group(db: Session, group_id: int, user_id: int) -> None:
    """
    Разрешаем просмотр транзакций для archived/soft-deleted групп.
    Требуем: группа существует (включая soft-deleted) и юзер — активный участник (membership не удалён).
    """
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    is_member = db.scalar(
        select(func.count()).select_from(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
            GroupMember.deleted_at.is_(None),
        )
    )
    if not is_member:
        raise HTTPException(status_code=403, detail="User is not a group member")

# ===== Хелперы снапшотов/идемпотентности для логов ============================

_LOG_FIELDS = (
    "type", "amount", "currency_code", "date", "comment",
    "category_id", "paid_by", "split_type", "transfer_from", "transfer_to", "receipt_url",
)

def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

def _shares_list_from_aggregated(agg: Dict[int, Dict[str, Decimal | int | None]], decimals: int):
    items = []
    for uid, payload in agg.items():
        items.append({
            "user_id": uid,
            "amount": str(q(Decimal(str(payload["amount"])), decimals)),
            "shares": int(payload["shares"]) if payload.get("shares") else None,
        })
    return sorted(items, key=lambda x: x["user_id"])

def _shares_list_from_tx(tx: Transaction, decimals_fallback: int = 2):
    items = []
    for s in (tx.shares or []):
        # amount может быть Decimal — сериализуем как строку
        amt = s.amount
        if isinstance(amt, Decimal):
            amt_str = str(amt)
        else:
            # на всякий — в строку
            amt_str = str(Decimal(str(amt)) if amt is not None else "0")
        items.append({
            "user_id": s.user_id,
            "amount": amt_str,
            "shares": int(s.shares) if s.shares is not None else None,
        })
    return sorted(items, key=lambda x: x["user_id"])

def _tx_snapshot_core(tx: Transaction, shares_list: List[Dict]) -> Dict:
    snap = {k: getattr(tx, k, None) for k in _LOG_FIELDS}
    # amount может быть Decimal
    if isinstance(snap.get("amount"), Decimal):
        snap["amount"] = str(snap["amount"])
    # transfer_to — лист int
    snap["transfer_to"] = list(tx.transfer_to or []) if getattr(tx, "transfer_to", None) else []
    snap["shares"] = shares_list
    return snap

def _tx_payload_for_created(tx: Transaction, decimals_fallback: int = 2) -> Dict:
    shares = _shares_list_from_tx(tx, decimals_fallback)
    payload = _tx_snapshot_core(tx, shares)
    payload["transaction_id"] = tx.id
    payload["group_id"] = tx.group_id
    return payload

# ===== Схемы для входа (привязка URL чека) ===================================

class ReceiptUrlIn(BaseModel):
    # принимаем любую непустую строку; относительную превратим в абсолютную
    url: constr(strip_whitespace=True, min_length=1)

# ===== Эндпоинты ==============================================================

@router.get("/", response_model=List[TransactionOut])
def get_transactions(
    db: Session = Depends(get_db),
    response: Response = None,
    request: Request = None,
    current_user=Depends(get_current_telegram_user),
    group_id: Optional[int] = Query(None, description="Фильтр по группе"),
    user_id: Optional[int] = Query(None, description="Фильтр по пользователю (разрешён только current_user)"),
    type: Optional[str] = Query(None, description="Фильтр по типу транзакции ('expense'|'transfer')"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    qy = (
        db.query(Transaction)
        .filter(Transaction.is_deleted.is_(False))
        .options(
            joinedload(Transaction.category),
            selectinload(Transaction.shares),
        )
    )

    if group_id is not None:
        # ВАЖНО: допускаем просмотр даже если группа soft-deleted/archived
        _require_membership_incl_deleted_group(db, group_id, current_user.id)
        qy = qy.filter(Transaction.group_id == group_id)

    if type:
        qy = qy.filter(Transaction.type == type)

    if user_id is not None:
        if user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Filtering by another user is forbidden")
        share_tx_ids_subq = (
            db.query(TransactionShare.transaction_id)
            .filter(TransactionShare.user_id == user_id)
            .subquery()
        )
        from sqlalchemy import select as _select
        qy = qy.filter(
            (Transaction.created_by == user_id)
            | (Transaction.paid_by == user_id)
            | (Transaction.transfer_from == user_id)
            | (Transaction.id.in_(_select(share_tx_ids_subq)))
        )

    total = qy.count()
    items = (
        qy.order_by(Transaction.date.desc(), Transaction.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    for tx in items:
        _attach_related_users(db, tx)
        # Нормализуем receipt_url в абсолютный
        if getattr(tx, "receipt_url", None) and request is not None:
            tx.receipt_url = to_abs_media_url(tx.receipt_url, request)

    if response is not None:
        response.headers["X-Total-Count"] = str(total)
    return items


@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    request: Request = None,
    current_user=Depends(get_current_telegram_user),
):
    tx = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.category),
            selectinload(Transaction.shares),
        )
        .filter(
            Transaction.id == transaction_id,
            Transaction.is_deleted.is_(False),
        )
        .first()
    )
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")

    # Разрешаем просмотр даже если группа soft-deleted/archived
    _require_membership_incl_deleted_group(db, tx.group_id, current_user.id)

    _attach_related_users(db, tx)
    if getattr(tx, "receipt_url", None) and request is not None:
        tx.receipt_url = to_abs_media_url(tx.receipt_url, request)
    return tx


@router.post("/", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    tx: TransactionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    group = guard_mutation_for_member(db, tx.group_id, current_user.id)
    ensure_group_active(group)

    tx_currency = (tx.currency_code or getattr(group, "default_currency_code", None) or "").strip().upper()
    if not tx_currency:
        raise HTTPException(status_code=422, detail="currency_code is required (or group must have default_currency_code)")
    decimals = get_currency_decimals(db, tx_currency)

    if tx.category_id is not None:
        allowed_ids = get_allowed_category_ids(db, tx.group_id)
        if not is_category_allowed(allowed_ids, tx.category_id):
            raise HTTPException(status_code=403, detail="Category is not allowed for this group")

    member_ids = set(get_group_member_ids(db, tx.group_id))

    if tx.type == "expense":
        if tx.paid_by is None:
            raise HTTPException(status_code=422, detail="paid_by is required for expense")
        if tx.paid_by not in member_ids:
            raise HTTPException(status_code=400, detail="paid_by must be a member of the group")
        if tx.transfer_from is not None or (tx.transfer_to and len(tx.transfer_to) > 0):
            raise HTTPException(status_code=422, detail="transfer_from/transfer_to are not allowed for expense")
    elif tx.type == "transfer":
        if tx.transfer_from is None or not tx.transfer_to:
            raise HTTPException(status_code=422, detail="transfer_from and a non-empty transfer_to are required for transfer")
        if tx.transfer_from not in member_ids:
            raise HTTPException(status_code=400, detail="transfer_from must be a member of the group")
        if any(uid not in member_ids for uid in tx.transfer_to):
            raise HTTPException(status_code=400, detail="All transfer_to users must be group members")

    aggregated_shares: Dict[int, Dict[str, Decimal | int | None]] = {}
    if tx.shares:
        for share in tx.shares:
            uid = share.user_id
            if uid not in member_ids:
                raise HTTPException(status_code=400, detail=f"User {uid} is not a member of the group")
            entry = aggregated_shares.setdefault(uid, {"amount": Decimal("0"), "shares": 0})
            entry["amount"] = q(Decimal(str(entry["amount"])) + Decimal(str(share.amount)), decimals)
            if share.shares is not None:
                entry["shares"] = int(entry["shares"]) + int(share.shares)

    total_amount = q(Decimal(str(tx.amount)), decimals)
    if aggregated_shares:
        total_shares = q(sum((Decimal(str(p["amount"])) for p in aggregated_shares.values()), Decimal("0")), decimals)
        if total_shares != total_amount:
            raise HTTPException(
                status_code=422,
                detail=f"Sum of shares ({total_shares}) must equal transaction amount ({total_amount})",
            )

    tx_dict = tx.model_dump(exclude={"shares"})
    tx_dict["created_by"] = current_user.id
    tx_dict["currency_code"] = tx_currency
    new_tx = Transaction(**tx_dict)
    db.add(new_tx)
    db.flush()  # получим new_tx.id

    if aggregated_shares:
        shares_objs = []
        for uid, payload in aggregated_shares.items():
            shares_objs.append(
                TransactionShare(
                    transaction_id=new_tx.id,
                    user_id=uid,
                    amount=q(Decimal(str(payload["amount"])), decimals),
                    shares=int(payload["shares"]) if payload["shares"] else None,
                )
            )
        db.add_all(shares_objs)

    # ---- ЛОГ: создание транзакции (в той же транзакции) ----------------------
    # payload — «снапшот» создаваемой транзакции.
    payload = {
        "id": None,  # для читаемости — ниже переопределим
        "group_id": new_tx.group_id,
        "type": new_tx.type,
        "amount": str(total_amount),
        "currency_code": tx_currency,
        "date": new_tx.date,
        "comment": new_tx.comment,
        "category_id": new_tx.category_id,
        "paid_by": new_tx.paid_by,
        "split_type": new_tx.split_type,
        "transfer_from": new_tx.transfer_from,
        "transfer_to": list(new_tx.transfer_to or []),
        "shares": _shares_list_from_aggregated(aggregated_shares, decimals) if aggregated_shares else [],
    }
    payload["id"] = new_tx.id
    idk = f"tx:{new_tx.id}:created"

    log_event(
        db,
        type=TRANSACTION_CREATED,
        actor_id=current_user.id,
        group_id=new_tx.group_id,
        target_user_id=None,
        data=payload,
        transaction_id=new_tx.id,
        idempotency_key=idk,
    )

    db.commit()

    new_tx = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.category),
            selectinload(Transaction.shares),
        )
        .filter(Transaction.id == new_tx.id)
        .first()
    )
    _attach_related_users(db, new_tx)
    return new_tx


@router.put("/{transaction_id}", response_model=TransactionOut)
def update_transaction(
    transaction_id: int,
    patch: TransactionUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    tx = (
        db.query(Transaction)
        .options(selectinload(Transaction.shares))
        .filter(Transaction.id == transaction_id, Transaction.is_deleted.is_(False))
        .first()
    )
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")

    require_membership(db, tx.group_id, current_user.id)
    group = guard_mutation_for_member(db, tx.group_id, current_user.id)
    ensure_group_active(group)

    inactive = _inactive_participants(db, tx.group_id, tx)
    if inactive:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "tx_has_inactive_participants",
                "inactive_participants": [UserOut.from_orm(u).dict() for u in inactive],
            },
        )

    if patch.type and patch.type != tx.type:
        raise HTTPException(status_code=409, detail="Changing transaction type is not allowed")

    new_currency_code = (patch.currency_code or tx.currency_code or getattr(group, "default_currency_code", None) or "").strip().upper()
    if not new_currency_code:
        raise HTTPException(status_code=422, detail="currency_code is required")
    decimals = get_currency_decimals(db, new_currency_code)

    if patch.category_id is not None:
        allowed_ids = get_allowed_category_ids(db, tx.group_id)
        if not is_category_allowed(allowed_ids, patch.category_id):
            raise HTTPException(status_code=403, detail="Category is not allowed for this group")

    member_ids = set(get_group_member_ids(db, tx.group_id))

    if tx.type == "expense":
        if patch.paid_by is None:
            raise HTTPException(status_code=422, detail="paid_by is required for expense")
        if patch.paid_by not in member_ids:
            raise HTTPException(status_code=400, detail="paid_by must be a member of the group")
        if patch.transfer_from is not None or (patch.transfer_to and len(patch.transfer_to) > 0):
            raise HTTPException(status_code=422, detail="transfer_from/transfer_to are not allowed for expense")
    elif tx.type == "transfer":
        if patch.transfer_from is None or not patch.transfer_to:
            raise HTTPException(status_code=422, detail="transfer_from and a non-empty transfer_to are required for transfer")
        if patch.transfer_from not in member_ids:
            raise HTTPException(status_code=400, detail="transfer_from must be a member of the group")
        if any(uid not in member_ids for uid in patch.transfer_to):
            raise HTTPException(status_code=400, detail="All transfer_to users must be group members")

    # ---- SNAPSHOT "до" -------------------------------------------------------
    before_shares = _shares_list_from_tx(tx, decimals)
    before = _tx_snapshot_core(tx, before_shares)

    # ---- Применяем изменения --------------------------------------------------
    aggregated_shares: Dict[int, Dict[str, Decimal | int | None]] = {}
    if patch.shares:
        for share in patch.shares:
            uid = share.user_id
            if uid not in member_ids:
                raise HTTPException(status_code=400, detail=f"User {uid} is not a member of the group")
            entry = aggregated_shares.setdefault(uid, {"amount": Decimal("0"), "shares": 0})
            entry["amount"] = q(Decimal(str(entry["amount"])) + Decimal(str(share.amount)), decimals)
            if share.shares is not None:
                entry["shares"] = int(entry["shares"]) + int(share.shares)

    total_amount = q(Decimal(str(patch.amount)), decimals)
    if aggregated_shares:
        total_shares = q(sum((Decimal(str(p["amount"])) for p in aggregated_shares.values()), Decimal("0")), decimals)
        if total_shares != total_amount:
            raise HTTPException(
                status_code=422,
                detail=f"Sum of shares ({total_shares}) must equal transaction amount ({total_amount})",
            )

    tx.amount = total_amount
    if patch.currency_code:
        tx.currency_code = new_currency_code
    tx.date = patch.date
    tx.comment = patch.comment

    if tx.type == "expense":
        tx.category_id = patch.category_id
        tx.paid_by = patch.paid_by
        tx.split_type = patch.split_type
        tx.transfer_from = None
        tx.transfer_to = None
    else:
        tx.transfer_from = patch.transfer_from
        tx.transfer_to = patch.transfer_to
        tx.split_type = None
        tx.category_id = None
        tx.paid_by = None

    # --- Поддержка receipt_* полей при апдейте (идемпотентно)
    if hasattr(patch, "receipt_url") and patch.receipt_url is not None:
        tx.receipt_url = (patch.receipt_url or None)
    if hasattr(patch, "receipt_data") and patch.receipt_data is not None:
        tx.receipt_data = (patch.receipt_data or None)

    db.query(TransactionShare).filter(TransactionShare.transaction_id == tx.id).delete()
    if aggregated_shares:
        shares_objs = []
        for uid, payload in aggregated_shares.items():
            shares_objs.append(
                TransactionShare(
                    transaction_id=tx.id,
                    user_id=uid,
                    amount=q(Decimal(str(payload["amount"])), decimals),
                    shares=int(payload["shares"]) if payload["shares"] else None,
                )
            )
        db.add_all(shares_objs)

    # ---- SNAPSHOT "после" (без дополнительного запроса) ----------------------
    after_tmp = Transaction()
    # копируем «видимые» поля
    for f in _LOG_FIELDS:
        setattr(after_tmp, f, getattr(tx, f, None))
    # shares на основе aggregated_shares, если они были переданы, иначе — прежние
    if aggregated_shares:
        after_shares = _shares_list_from_aggregated(aggregated_shares, decimals)
    else:
        after_shares = before_shares  # не менялись
    after = _tx_snapshot_core(after_tmp, after_shares)

    # ---- Дифф и лог ----------------------------------------------------------
    diff = make_tx_diff(before, after)
    if diff.get("changed"):
        idk = f"tx:{tx.id}:upd:{_short_hash(json.dumps(diff, sort_keys=True, default=str))}"
        log_event(
            db,
            type=TRANSACTION_UPDATED,
            actor_id=current_user.id,
            group_id=tx.group_id,
            target_user_id=None,
            data=diff,
            transaction_id=tx.id,
            idempotency_key=idk,
        )

    db.commit()

    tx = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.category),
            selectinload(Transaction.shares),
        )
        .filter(Transaction.id == tx.id)
        .first()
    )
    _attach_related_users(db, tx)
    return tx


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    tx = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")

    group = require_membership(db, tx.group_id, current_user.id)
    ensure_group_active(group)

    if tx.is_deleted:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    inactive = _inactive_participants(db, tx.group_id, tx)
    if inactive:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "tx_has_inactive_participants",
                "inactive_participants": [UserOut.from_orm(u).dict() for u in inactive],
            },
        )

    # Опционально: подчистим локальный файл чека при удалении транзакции
    old_receipt = tx.receipt_url

    tx.is_deleted = True
    tx.receipt_url = None
    db.commit()

    # Пытаемся удалить локальный файл чека (если он наш и существовал)
    delete_if_local(old_receipt, allowed_subdirs=("receipts",))

    return Response(status_code=status.HTTP_204_NO_CONTENT)

# ===== Новые эндпоинты: привязка/удаление чека ================================

@router.post("/{transaction_id}/receipt/url", response_model=TransactionOut)
def set_transaction_receipt_by_url(
    transaction_id: int,
    payload: ReceiptUrlIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
    request: Request = None,
):
    """
    Привязка чека по URL (относительный нормализуем в абсолютный).
    Доступ: любой участник активной группы.
    """
    tx = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.category),
            selectinload(Transaction.shares),
        )
        .filter(Transaction.id == transaction_id, Transaction.is_deleted.is_(False))
        .first()
    )
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")

    group = require_membership(db, tx.group_id, current_user.id)
    ensure_group_active(group)

    old_url = tx.receipt_url
    new_abs = str(to_abs_media_url(payload.url, request))

    # Определим тип события
    if not old_url and new_abs:
        evt_type = TRANSACTION_RECEIPT_ADDED
        idk = f"tx:{tx.id}:rcpt:add:{_short_hash(new_abs)}"
        evt_data = {"old_url": None, "new_url": new_abs}
    elif old_url and new_abs and old_url != new_abs:
        evt_type = TRANSACTION_RECEIPT_REPLACED
        idk = f"tx:{tx.id}:rcpt:repl:{_short_hash(old_url + '->' + new_abs)}"
        evt_data = {"old_url": old_url, "new_url": new_abs}
    else:
        # Ничего не меняется — просто вернём текущую
        if getattr(tx, "receipt_url", None) and request is not None:
            tx.receipt_url = to_abs_media_url(tx.receipt_url, request)
        _attach_related_users(db, tx)
        return tx

    # Применяем
    tx.receipt_url = new_abs

    # ЛОГ до коммита
    log_event(
        db,
        type=evt_type,
        actor_id=current_user.id,
        group_id=tx.group_id,
        target_user_id=None,
        data=evt_data,
        transaction_id=tx.id,
        idempotency_key=idk,
    )

    db.commit()
    db.refresh(tx)

    # Если старый файл был локальным и отличается от нового — удаляем его из ФС
    try:
        old_local = url_to_media_local_path(old_url, allowed_subdirs=("receipts",))
        new_local = url_to_media_local_path(tx.receipt_url, allowed_subdirs=("receipts",))
        if old_local and (not new_local or old_local != new_local):
            delete_if_local(old_url, allowed_subdirs=("receipts",))
    except Exception:
        pass

    # На выдачу — уже абсолютный URL
    if getattr(tx, "receipt_url", None) and request is not None:
        tx.receipt_url = to_abs_media_url(tx.receipt_url, request)
    _attach_related_users(db, tx)
    return tx


@router.delete("/{transaction_id}/receipt", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction_receipt(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_telegram_user),
):
    """
    Удаление привязанного чека (как у аватара группы):
      - любой участник,
      - только активная группа,
      - обнуляем receipt_url (и по желанию можно очистить receipt_data),
      - если файл локальный — пробуем удалить с диска.
    """
    tx = db.query(Transaction).filter(Transaction.id == transaction_id, Transaction.is_deleted.is_(False)).first()
    if not tx:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    group = require_membership(db, tx.group_id, current_user.id)
    ensure_group_active(group)

    old_url = tx.receipt_url
    if not old_url:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    tx.receipt_url = None
    # по желанию: tx.receipt_data = None

    # ЛОГ до коммита
    idk = f"tx:{tx.id}:rcpt:rm:{_short_hash(old_url)}"
    log_event(
        db,
        type=TRANSACTION_RECEIPT_REMOVED,
        actor_id=current_user.id,
        group_id=tx.group_id,
        target_user_id=None,
        data={"old_url": old_url},
        transaction_id=tx.id,
        idempotency_key=idk,
    )

    db.commit()

    delete_if_local(old_url, allowed_subdirs=("receipts",))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
