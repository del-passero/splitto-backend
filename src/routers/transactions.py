# src/routers/transactions.py
# РОУТЕР ТРАНЗАКЦИЙ — добавлена «склейка» дублей в shares перед вставкой

from __future__ import annotations

from typing import List, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from src.db import get_db
from src.models.transaction import Transaction
from src.models.transaction_share import TransactionShare
from src.models.group import Group
from src.models.expense_category import ExpenseCategory
from src.schemas.transaction import TransactionCreate, TransactionOut
from src.schemas.transaction_share import TransactionShareCreate, TransactionShareOut

# Авторизация (Telegram WebApp)
from src.utils.telegram_dep import get_current_telegram_user


# Общие гарды/хелперы по группам
from src.utils.groups import (
    require_membership,
    guard_mutation_for_member,
    get_group_member_ids,
    get_allowed_category_ids,
    is_category_allowed,
)

router = APIRouter()


@router.get("/", response_model=List[TransactionOut])
def get_transactions(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
    group_id: Optional[int] = Query(None, description="Фильтр по группе"),
    user_id: Optional[int] = Query(None, description="Фильтр по пользователю (разрешён только current_user)"),
    type: Optional[str] = Query(None, description="Фильтр по типу транзакции ('expense'|'transfer')"),
):
    q = db.query(Transaction).filter(Transaction.is_deleted.is_(False))

    if group_id is not None:
        require_membership(db, group_id, current_user.id)
        q = q.filter(Transaction.group_id == group_id)

    if type:
        q = q.filter(Transaction.type == type)

    if user_id is not None:
        if user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Filtering by another user is forbidden")
        q = (
            q.outerjoin(TransactionShare)
            .filter(
                (Transaction.created_by == user_id)
                | (Transaction.paid_by == user_id)
                | (Transaction.transfer_from == user_id)
                | (TransactionShare.user_id == user_id)
            )
        )

    return q.order_by(Transaction.date.desc(), Transaction.id.desc()).all()


@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    tx = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.is_deleted.is_(False),
    ).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")

    require_membership(db, tx.group_id, current_user.id)
    return tx


@router.post("/", response_model=TransactionOut)
def create_transaction(
    tx: TransactionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    """
    Создать транзакцию.
    Дополнительно к прежним проверкам — склеиваем дублирующиеся shares по user_id
    (суммируем amount и shares), чтобы не ловить 409 на уникальном индексе.
    """
    # 1) Автор — участник, группа активна
    group = guard_mutation_for_member(db, tx.group_id, current_user.id)

    # 2) Валюта транзакции = валюта группы (или подставляем её)
    tx_currency = (tx.currency or "").strip().upper()
    group_currency = (group.default_currency_code or "").strip().upper()
    if tx_currency:
        if group_currency and tx_currency != group_currency:
            raise HTTPException(status_code=409, detail="Transaction currency must match group currency")
    else:
        tx_currency = group_currency

    # 3) Категория (если указана) должна быть разрешена
    allowed_ids = get_allowed_category_ids(db, tx.group_id)
    if tx.category_id is not None and not is_category_allowed(allowed_ids, tx.category_id):
        raise HTTPException(status_code=403, detail="Category is not allowed for this group")

    # 4) Все участники в shares должны быть членами группы
    group_member_ids = set(get_group_member_ids(db, tx.group_id))

    # --- НОВОЕ: агрегируем дублирующиеся shares по user_id ---
    aggregated_shares: Dict[int, Dict[str, float | int]] = {}
    if tx.shares:
        for share in tx.shares:
            if share.user_id not in group_member_ids:
                raise HTTPException(status_code=400, detail=f"User {share.user_id} is not a member of the group")

            entry = aggregated_shares.setdefault(share.user_id, {"amount": 0.0, "shares": 0})
            entry["amount"] = float(entry["amount"]) + float(share.amount)
            # shares может быть None — суммируем только если есть число
            if share.shares is not None:
                entry["shares"] = int(entry["shares"]) + int(share.shares)

    # 5) Для 'expense' проверим paid_by на членство (если указан)
    if tx.type == "expense" and tx.paid_by is not None and tx.paid_by not in group_member_ids:
        raise HTTPException(status_code=400, detail="paid_by must be a member of the group")

    # 6) Создаём транзакцию
    tx_dict = tx.dict(exclude={"shares"})
    tx_dict["created_by"] = current_user.id
    tx_dict["currency"] = tx_currency
    new_tx = Transaction(**tx_dict)
    db.add(new_tx)
    db.flush()  # нужен id

    # 7) Вставляем доли (уже агрегированные)
    if aggregated_shares:
        shares_objs = []
        for uid, payload in aggregated_shares.items():
            shares_objs.append(TransactionShare(
                transaction_id=new_tx.id,
                user_id=uid,
                amount=float(payload["amount"]),
                shares=int(payload["shares"]) if payload["shares"] is not None else None
            ))
        db.add_all(shares_objs)

    db.commit()
    db.refresh(new_tx)
    return new_tx


@router.delete("/{transaction_id}", status_code=204)
def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_telegram_user),
):
    tx = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")

    from src.utils.groups import ensure_group_active
    group = require_membership(db, tx.group_id, current_user.id)
    ensure_group_active(group)

    if tx.is_deleted:
        return

    tx.is_deleted = True
    db.commit()
    return
