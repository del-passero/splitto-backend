# src/schemas/settlement.py

from pydantic import BaseModel

class SettlementOut(BaseModel):
    """
    Схема ответа для settle-up (жадного алгоритма оптимизации переводов).
    Используется для выдачи минимального набора переводов между участниками группы или в глобальном settle-up.
    """
    from_user_id: int  # id того, кто должен совершить перевод (должник)
    to_user_id: int    # id того, кому перевод предназначен (кредитор)
    amount: float      # сумма перевода (>0, округляется до 2 знаков)

    class Config:
        orm_mode = True
