"""
Идемпотентный сидинг валют. Запуск:
  $ python scripts/seed_currencies.py
"""
from __future__ import annotations
import os
import json
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

CURRENCIES = [
    {
        "code": "RUB", "numeric_code": 643, "decimals": 2, "symbol": "₽",
        "flag_emoji": "🇷🇺", "display_country": "RU",
        "name_i18n": {
            "en": "Russian Ruble",
            "ru": "Российский рубль",
            "es": "Rublo ruso"
        },
        "is_popular": True, "is_active": True,
    },
    {
        "code": "USD", "numeric_code": 840, "decimals": 2, "symbol": "$",
        "flag_emoji": "🇺🇸", "display_country": "US",
        "name_i18n": {
            "en": "US Dollar",
            "ru": "Доллар США",
            "es": "Dólar estadounidense"
        },
        "is_popular": True, "is_active": True,
    },
    {
        "code": "EUR", "numeric_code": 978, "decimals": 2, "symbol": "€",
        "flag_emoji": "🇪🇺", "display_country": "EU",
        "name_i18n": {
            "en": "Euro",
            "ru": "Евро",
            "es": "Euro"
        },
        "is_popular": True, "is_active": True,
    },
    {
        "code": "GBP", "numeric_code": 826, "decimals": 2, "symbol": "£",
        "flag_emoji": "🇬🇧", "display_country": "GB",
        "name_i18n": {
            "en": "British Pound",
            "ru": "Британский фунт",
            "es": "Libra esterlina"
        },
        "is_popular": True, "is_active": True,
    },
    {
        "code": "UAH", "numeric_code": 980, "decimals": 2, "symbol": "₴",
        "flag_emoji": "🇺🇦", "display_country": "UA",
        "name_i18n": {
            "en": "Ukrainian Hryvnia",
            "ru": "Украинская гривна",
            "es": "Grivna ucraniana"
        },
        "is_popular": True, "is_active": True,
    },
    {
        "code": "BYN", "numeric_code": 933, "decimals": 2, "symbol": "Br",
        "flag_emoji": "🇧🇾", "display_country": "BY",
        "name_i18n": {
            "en": "Belarusian Ruble",
            "ru": "Белорусский рубль",
            "es": "Rublo bielorruso"
        },
        "is_popular": False, "is_active": True,
    },
    {
        "code": "KZT", "numeric_code": 398, "decimals": 2, "symbol": "₸",
        "flag_emoji": "🇰🇿", "display_country": "KZ",
        "name_i18n": {
            "en": "Kazakhstani Tenge",
            "ru": "Казахстанский тенге",
            "es": "Tenge kazajo"
        },
        "is_popular": False, "is_active": True,
    },
    {
        "code": "CNY", "numeric_code": 156, "decimals": 2, "symbol": "¥",
        "flag_emoji": "🇨🇳", "display_country": "CN",
        "name_i18n": {
            "en": "Chinese Yuan",
            "ru": "Китайский юань",
            "es": "Yuan chino"
        },
        "is_popular": True, "is_active": True,
    },
    {
        "code": "TRY", "numeric_code": 949, "decimals": 2, "symbol": "₺",
        "flag_emoji": "🇹🇷", "display_country": "TR",
        "name_i18n": {
            "en": "Turkish Lira",
            "ru": "Турецкая лира",
            "es": "Lira turca"
        },
        "is_popular": False, "is_active": True,
    },
]

UPSERT_SQL = """
INSERT INTO currencies (
    code, numeric_code, decimals, symbol, flag_emoji, display_country,
    name_i18n, is_popular, is_active, created_at, updated_at
)
VALUES (
    :code, :numeric_code, :decimals, :symbol, :flag_emoji, :display_country,
    CAST(:name_i18n AS jsonb), :is_popular, :is_active, now(), now()
)
ON CONFLICT (code) DO UPDATE
SET numeric_code = EXCLUDED.numeric_code,
    decimals = EXCLUDED.decimals,
    symbol = EXCLUDED.symbol,
    flag_emoji = EXCLUDED.flag_emoji,
    display_country = EXCLUDED.display_country,
    name_i18n = EXCLUDED.name_i18n,
    is_popular = EXCLUDED.is_popular,
    is_active = EXCLUDED.is_active,
    updated_at = now();
"""

def main():
    with engine.begin() as conn:
        for c in CURRENCIES:
            params = {**c, "name_i18n": json.dumps(c["name_i18n"])}
            conn.execute(text(UPSERT_SQL), params)
            print(f"Seeded {c['code']}")
    print("Currencies seeded ✔")

if __name__ == "__main__":
    main()
