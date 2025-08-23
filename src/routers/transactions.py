# src/routers/transactions.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from starlette import status
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import select

from src.db import get_db
from src.models.transaction import Transaction
from src.models.transaction_share import TransactionShare
from src.schemas.transaction import TransactionCreate, TransactionUpdate, TransactionOut

from src.utils.telegram_dep import get_current_telegram_user
from src.utils.groups import (
  require_membership,
  guard_mutation_for_member,
  get_group_member_ids,
  get_allowed_category_ids,
  is_category_allowed,
  ensure_group_active,
)

router = APIRouter()

def q2(x: Decimal) -> Decimal:
  return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

@router.get("/", response_model=List[TransactionOut])
def get_transactions(
  db: Session = Depends(get_db),
  response: Response = None,
  current_user=Depends(get_current_telegram_user),
  group_id: Optional[int] = Query(None, description="Фильтр по группе"),
  user_id: Optional[int] = Query(None, description="Фильтр по пользователю (разрешён только current_user)"),
  type: Optional[str] = Query(None, description="Фильтр по типу транзакции ('expense'|'transfer')"),
  offset: int = Query(0, ge=0),
  limit: int = Query(20, ge=1, le=100),
):
  q = (
    db.query(Transaction)
    .filter(Transaction.is_deleted.is_(False))
    .options(
      joinedload(Transaction.category),
      selectinload(Transaction.shares),
    )
  )

  if group_id is not None:
    require_membership(db, group_id, current_user.id)
    q = q.filter(Transaction.group_id == group_id)

  if type:
    q = q.filter(Transaction.type == type)

  if user_id is not None:
    if user_id != current_user.id:
      raise HTTPException(status_code=403, detail="Filtering by another user is forbidden")
    share_tx_ids_subq = (
      db.query(TransactionShare.transaction_id)
      .filter(TransactionShare.user_id == user_id)
      .subquery()
    )
    q = q.filter(
      (Transaction.created_by == user_id)
      | (Transaction.paid_by == user_id)
      | (Transaction.transfer_from == user_id)
      | (Transaction.id.in_(select(share_tx_ids_subq)))
    )

  total = q.count()
  items = (
    q.order_by(Transaction.date.desc(), Transaction.id.desc())
    .offset(offset)
    .limit(limit)
    .all()
  )

  if response is not None:
    response.headers["X-Total-Count"] = str(total)
  return items

@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(
  transaction_id: int,
  db: Session = Depends(get_db),
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

  require_membership(db, tx.group_id, current_user.id)
  return tx

@router.post("/", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
  tx: TransactionCreate,
  db: Session = Depends(get_db),
  current_user=Depends(get_current_telegram_user),
):
  group = guard_mutation_for_member(db, tx.group_id, current_user.id)
  ensure_group_active(group)

  tx_currency = (tx.currency or "").strip().upper()
  group_currency = (getattr(group, "default_currency_code", None) or "").strip().upper()
  if tx_currency:
    if group_currency and tx_currency != group_currency:
      raise HTTPException(status_code=409, detail="Transaction currency must match group currency")
  else:
    tx_currency = group_currency
  tx_currency = tx_currency or None

  if tx.category_id is not None:
    allowed_ids = get_allowed_category_ids(db, tx.group_id)
    if not is_category_allowed(allowed_ids, tx.category_id):
      raise HTTPException(status_code=403, detail="Category is not allowed for this group")

  group_member_ids = set(get_group_member_ids(db, tx.group_id))

  if tx.type == "expense":
    if tx.paid_by is None:
      raise HTTPException(status_code=422, detail="paid_by is required for expense")
    if tx.paid_by not in group_member_ids:
      raise HTTPException(status_code=400, detail="paid_by must be a member of the group")
    if tx.transfer_from is not None or (tx.transfer_to and len(tx.transfer_to) > 0):
      raise HTTPException(status_code=422, detail="transfer_from/transfer_to are not allowed for expense")

  elif tx.type == "transfer":
    if tx.transfer_from is None or not tx.transfer_to:
      raise HTTPException(status_code=422, detail="transfer_from and a non-empty transfer_to are required for transfer")
    if tx.transfer_from not in group_member_ids:
      raise HTTPException(status_code=400, detail="transfer_from must be a member of the group")
    if any(uid not in group_member_ids for uid in tx.transfer_to):
      raise HTTPException(status_code=400, detail="All transfer_to users must be group members")

  aggregated_shares: Dict[int, Dict[str, Decimal | int | None]] = {}
  if tx.shares:
    for share in tx.shares:
      uid = share.user_id
      if uid not in group_member_ids:
        raise HTTPException(status_code=400, detail=f"User {uid} is not a member of the group")

      entry = aggregated_shares.setdefault(uid, {"amount": Decimal("0.00"), "shares": 0})
      entry["amount"] = q2(Decimal(str(entry["amount"])) + Decimal(str(share.amount)))
      if share.shares is not None:
        entry["shares"] = int(entry["shares"]) + int(share.shares)

  total_amount = q2(Decimal(str(tx.amount)))
  if aggregated_shares:
    total_shares = q2(sum((Decimal(str(p["amount"])) for p in aggregated_shares.values()), Decimal("0.00")))
    if total_shares != total_amount:
      raise HTTPException(
        status_code=422,
        detail=f"Sum of shares ({total_shares}) must equal transaction amount ({total_amount})",
      )

  tx_dict = tx.model_dump(exclude={"shares"})
  tx_dict["created_by"] = current_user.id
  tx_dict["currency"] = tx_currency
  new_tx = Transaction(**tx_dict)
  db.add(new_tx)
  db.flush()

  if aggregated_shares:
    shares_objs = []
    for uid, payload in aggregated_shares.items():
      shares_objs.append(
        TransactionShare(
          transaction_id=new_tx.id,
          user_id=uid,
          amount=q2(Decimal(str(payload["amount"]))),
          shares=int(payload["shares"]) if payload["shares"] else None,
        )
      )
    db.add_all(shares_objs)

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

  if patch.type and patch.type != tx.type:
    raise HTTPException(status_code=409, detail="Changing transaction type is not allowed")

  patch_currency = (patch.currency or "").strip().upper()
  group_currency = (getattr(group, "default_currency_code", None) or "").strip().upper()
  if patch_currency:
    if group_currency and patch_currency != group_currency:
      raise HTTPException(status_code=409, detail="Transaction currency must match group currency")
  else:
    patch_currency = group_currency
  patch_currency = patch_currency or None

  if patch.category_id is not None:
    allowed_ids = get_allowed_category_ids(db, tx.group_id)
    if not is_category_allowed(allowed_ids, patch.category_id):
      raise HTTPException(status_code=403, detail="Category is not allowed for this group")

  group_member_ids = set(get_group_member_ids(db, tx.group_id))

  if tx.type == "expense":
    if patch.paid_by is None:
      raise HTTPException(status_code=422, detail="paid_by is required for expense")
    if patch.paid_by not in group_member_ids:
      raise HTTPException(status_code=400, detail="paid_by must be a member of the group")
    if patch.transfer_from is not None or (patch.transfer_to and len(patch.transfer_to) > 0):
      raise HTTPException(status_code=422, detail="transfer_from/transfer_to are not allowed for expense")

  elif tx.type == "transfer":
    if patch.transfer_from is None or not patch.transfer_to:
      raise HTTPException(status_code=422, detail="transfer_from and a non-empty transfer_to are required for transfer")
    if patch.transfer_from not in group_member_ids:
      raise HTTPException(status_code=400, detail="transfer_from must be a member of the group")
    if any(uid not in group_member_ids for uid in patch.transfer_to):
      raise HTTPException(status_code=400, detail="All transfer_to users must be group members")

  aggregated_shares: Dict[int, Dict[str, Decimal | int | None]] = {}
  if patch.shares:
    for share in patch.shares:
      uid = share.user_id
      if uid not in group_member_ids:
        raise HTTPException(status_code=400, detail=f"User {uid} is not a member of the group")
      entry = aggregated_shares.setdefault(uid, {"amount": Decimal("0.00"), "shares": 0})
      entry["amount"] = q2(Decimal(str(entry["amount"])) + Decimal(str(share.amount)))
      if share.shares is not None:
        entry["shares"] = int(entry["shares"]) + int(share.shares)

  total_amount = q2(Decimal(str(patch.amount)))
  if aggregated_shares:
    total_shares = q2(sum((Decimal(str(p["amount"])) for p in aggregated_shares.values()), Decimal("0.00")))
    if total_shares != total_amount:
      raise HTTPException(
        status_code=422,
        detail=f"Sum of shares ({total_shares}) must equal transaction amount ({total_amount})",
      )

  tx.amount = total_amount
  tx.currency = patch_currency
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

  db.query(TransactionShare).filter(TransactionShare.transaction_id == tx.id).delete()
  if aggregated_shares:
    shares_objs = []
    for uid, payload in aggregated_shares.items():
      shares_objs.append(
        TransactionShare(
          transaction_id=tx.id,
          user_id=uid,
          amount=q2(Decimal(str(payload["amount"]))),
          shares=int(payload["shares"]) if payload["shares"] else None,
        )
      )
    db.add_all(shares_objs)

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

  if current_user.id not in {tx.created_by, tx.paid_by}:
    raise HTTPException(status_code=403, detail="Only author or payer can delete the transaction")

  tx.is_deleted = True
  db.commit()
  return Response(status_code=status.HTTP_204_NO_CONTENT)
