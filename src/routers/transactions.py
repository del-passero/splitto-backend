# src/routers/transactions.py

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from src.db import get_db
from src.models.transaction import Transaction
from src.models.transaction_share import TransactionShare
from src.schemas.transaction import TransactionCreate, TransactionOut
from src.schemas.transaction_share import TransactionShareCreate, TransactionShareOut

router = APIRouter()

def get_current_user_id(x_user_id: int = Header(...)):
    """
    Временно получаем user_id из заголовка x-user-id.
    В будущем заменить на полноценную авторизацию.
    """
    return x_user_id

@router.get("/", response_model=List[TransactionOut])
def get_transactions(
    db: Session = Depends(get_db),
    group_id: Optional[int] = None,
    user_id: Optional[int] = None,
    type: Optional[str] = None
):
    """
    Получить список транзакций (фильтры: по группе, по пользователю, по типу).
    """
    q = db.query(Transaction)
    if group_id:
        q = q.filter(Transaction.group_id == group_id)
    if type:
        q = q.filter(Transaction.type == type)
    if user_id:
        q = q.outerjoin(TransactionShare).filter(
            (Transaction.created_by == user_id) |
            (Transaction.paid_by == user_id) |
            (Transaction.transfer_from == user_id) |
            (TransactionShare.user_id == user_id)
        )
    return q.order_by(Transaction.date.desc()).all()

@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """
    Получить подробности одной транзакции (все поля, включая доли и категорию).
    """
    tx = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    return tx

@router.post("/", response_model=TransactionOut)
def create_transaction(
    tx: TransactionCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Создать новую транзакцию (расход или транш).
    created_by выставляется автоматически по user_id из авторизации.
    """
    tx_dict = tx.dict(exclude={"shares"})
    tx_dict["created_by"] = user_id  # <-- всегда проставляем на бэке!
    new_tx = Transaction(**tx_dict)
    db.add(new_tx)
    db.flush()  # чтобы получить id новой транзакции

    # Если есть доли — создаём объекты TransactionShare
    if tx.shares:
        shares_objs = []
        for share in tx.shares:
            share_obj = TransactionShare(
                transaction_id=new_tx.id,
                user_id=share.user_id,
                amount=share.amount,
                shares=share.shares
            )
            shares_objs.append(share_obj)
        db.add_all(shares_objs)
    db.commit()
    db.refresh(new_tx)
    return new_tx

@router.delete("/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """
    Удалить транзакцию (soft-delete через is_deleted или физически).
    """
    tx = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    db.delete(tx)
    db.commit()
    return
