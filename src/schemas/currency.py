# src/schemas/currency.py
# СХЕМЫ: справочник валют.
# ВАЖНО:
#   - CurrencyOut включает ВСЕ ключевые поля, в т.ч. name_i18n (для отладки/админки).
#   - В публичных ручках (GET /currencies) мы обычно возвращаем локализованное поле name,
#     вычисляя его в роутере на основании locale (coalesce(name_i18n[locale], name_i18n['en'])).

from __future__ import annotations

from typing import Dict, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class CurrencyOut(BaseModel):
    code: str = Field(..., description="Код валюты ISO-4217, напр. 'USD'")
    numeric_code: int = Field(..., description="Числовой код ISO-4217, напр. 840 для USD")
    decimals: int = Field(..., description="Количество знаков после запятой (2 для USD, 0 для JPY)")
    symbol: Optional[str] = Field(None, description="Символ валюты (например, '$', '€')")
    flag_emoji: Optional[str] = Field(None, description="Эмодзи флага региона валюты")
    display_country: Optional[str] = Field(None, description="Код страны/региона для показа флага, например 'US', 'EU'")
    name_i18n: Dict[str, str] = Field(..., description="Локализованные названия валют, ключ — код языка")
    is_popular: bool = Field(False, description="Популярная валюта (для ТОП списка)")
    is_active: bool = Field(True, description="Активная валюта")

    created_at: datetime = Field(..., description="Когда запись создана")
    updated_at: datetime = Field(..., description="Когда запись обновлена")

    class Config:
        from_attributes = True


class CurrencyLocalizedOut(BaseModel):
    # Вариант ответа уже с вычисленным 'name' для конкретной локали.
    # Можно использовать в публичных GET /currencies* ручках, чтобы не возвращать весь name_i18n.
    code: str = Field(..., description="Код валюты ISO-4217")
    numeric_code: int = Field(..., description="Числовой код ISO-4217")
    name: str = Field(..., description="Локализованное имя валюты для нужной локали")
    symbol: Optional[str] = Field(None, description="Символ валюты")
    decimals: int = Field(..., description="Количество знаков после запятой")
    flag_emoji: Optional[str] = Field(None, description="Эмодзи флага региона валюты")
    is_popular: bool = Field(False, description="Популярная валюта (для ТОП списка)")
