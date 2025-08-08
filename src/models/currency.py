# src/models/currency.py
# МОДЕЛЬ: Справочник валют (ISO-4217 + CLDR)
# ЦЕЛИ:
#   - Хранить код валюты, числовой код, количество знаков, символ, флаг/регион, локализованные названия.
#   - Отдавать на фронт «популярные» и «все», поддерживать поиск по локали/коду.
#   - В группе хранить default_currency_code (FK на code из этой таблицы).
#
# ПРИМЕЧАНИЯ:
#   - name_i18n — JSONB с ключами языков ("en", "ru", "es" ...). Это удобно для выборки локализованного имени.
#   - numeric_code в ISO-4217 уникален; делаем UniqueConstraint.
#   - В будущем можно добавить таблицу курсов (exchange_rates), но сейчас не требуется.

from __future__ import annotations

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    UniqueConstraint,
    Index,
    SmallInteger,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from ..db import Base


class Currency(Base):
    __tablename__ = "currencies"

    # Текстовый код валюты (ISO-4217), пример: "USD", "EUR", "AED"
    code = Column(
        String(3),
        primary_key=True,
        comment="Код валюты ISO-4217 (PK), пример: 'USD'",
    )

    # Числовой код ISO-4217, пример: 840 (USD), 978 (EUR)
    numeric_code = Column(
        SmallInteger,
        nullable=False,
        comment="Числовой код ISO-4217, пример: 840 для USD",
    )

    # Количество знаков после запятой (2 для USD, 0 для JPY и т.п.)
    decimals = Column(
        SmallInteger,
        nullable=False,
        comment="Число десятичных знаков (2 для USD, 0 для JPY и т.п.)",
    )

    # Символ валюты (€, $, ₽). Узкий символ (symbol_narrow) можно держать здесь же или добавить поле позже.
    symbol = Column(
        String(8),
        nullable=True,
        comment="Символ валюты (например, '$', '€', '₽')",
    )

    # Флаг/эмодзи основного региона (🇺🇸 для USD, 🇪🇺 для EUR, 🇯🇵 для JPY)
    flag_emoji = Column(
        String(8),
        nullable=True,
        comment="Эмодзи флага региона валюты (например, '🇺🇸')",
    )

    # Буквенный код страны для отображения флага (ISO-3166-1 alpha-2), напр. 'US', 'EU', 'JP'
    display_country = Column(
        String(2),
        nullable=True,
        comment="Код страны/региона для показа флага, например 'US', 'EU'",
    )

    # Локализованные названия валют: {"en": "US Dollar", "ru": "Доллар США", "es": "Dólar estadounidense"}
    name_i18n = Column(
        JSONB,
        nullable=False,
        comment="Локализованные названия валют в формате JSON (ключ — код языка)",
    )

    # Пометка «популярная» — для быстрых списков на фронте
    is_popular = Column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="Популярная валюта (показывать в топе)",
    )

    # Активность записи (мало ли, захочется выключать редкие или устаревшие)
    is_active = Column(
        Boolean,
        nullable=False,
        server_default="true",
        comment="Активная валюта",
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Время создания записи",
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Время последнего обновления записи",
    )

    __table_args__ = (
        UniqueConstraint("numeric_code", name="uq_currencies_numeric_code"),
        Index("ix_currencies_is_popular", "is_popular"),
        Index("ix_currencies_is_active", "is_active"),
        Index("ix_currencies_numeric_code", "numeric_code"),
        # Поиск по локализованным названиям будем делать на уровне SQL (->>locale ILIKE ...),
        # отдельный GIN-индекс по name_i18n не обязателен на старте.
    )
