# src/db.py
# Инициализация SQLAlchemy: движок, сессии, Base и явные импорты моделей.
# Что изменено:
#  • Добавлены импорты НОВЫХ моделей: currency, group_hidden, group_category
#    (это нужно, чтобы таблицы попали в metadata и были видны Alembic).
from __future__ import annotations

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Пул соединений — оставляем как в текущей конфигурации
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=20,
    pool_timeout=60,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ВАЖНО: Явные импорты всех моделей, чтобы они зарегистрировались в metadata.
# Добавлены: currency, group_hidden, group_category.
from src.models import (
    expense_category,
    transaction,
    transaction_share,
    user,
    group,
    group_member,
    friend,
    group_invite,
    friend_invite,
    invite_usage,
    event,
    currency,        # NEW
    group_hidden,    # NEW
    group_category,  # NEW
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
