from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.db import get_db
from src.models.expense_category import ExpenseCategory
from src.schemas.expense_category import ExpenseCategoryOut, ExpenseCategoryCreate
from typing import List

router = APIRouter()

@router.get("/", response_model=List[ExpenseCategoryOut])
def get_categories(db: Session = Depends(get_db)):
    """
    Получить все категории расходов (для селектора на фронте).
    """
    return db.query(ExpenseCategory).all()

# --- если нужно, можно добавить создание категорий для админки ---
# @router.post("/", response_model=ExpenseCategoryOut)
# def create_category(category: ExpenseCategoryCreate, db: Session = Depends(get_db)):
#     new_category = ExpenseCategory(**category.dict())
#     db.add(new_category)
#     db.commit()
#     db.refresh(new_category)
#     return new_category
