from sqlalchemy import Column, Integer, String
from src.db import Base

class ExpenseCategory(Base):
    """
    Категория расходов — справочник, используется для аналитики и UI.
    Например: Еда, Транспорт, Путешествия, ...
    """
    __tablename__ = "expense_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, comment="Название категории (например, 'Еда')")
    icon = Column(String, nullable=True, comment="Иконка или emoji категории (например, '🍕' или 'food')")
