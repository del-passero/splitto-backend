from pydantic import BaseModel

class ExpenseCategoryBase(BaseModel):
    """
    Базовая схема категории расходов (общие поля).
    """
    name: str
    icon: str | None = None  # emoji или иконка (по желанию)

class ExpenseCategoryCreate(ExpenseCategoryBase):
    """
    Схема для создания новой категории (если когда-нибудь потребуется).
    """
    pass

class ExpenseCategoryOut(ExpenseCategoryBase):
    """
    Схема для вывода категории наружу (на фронт).
    """
    id: int

    class Config:
        orm_mode = True
