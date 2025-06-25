from pydantic import BaseModel

class TransactionShareBase(BaseModel):
    """
    Базовая схема доли по расходу/транзакции.
    """
    user_id: int
    amount: float
    shares: int | None = None  # число долей (для split_type='shares')

class TransactionShareCreate(TransactionShareBase):
    """
    Схема для создания доли (используется при создании транзакции).
    """
    pass

class TransactionShareOut(TransactionShareBase):
    """
    Схема для выдачи доли наружу (на фронт).
    """
    id: int

    class Config:
        orm_mode = True
