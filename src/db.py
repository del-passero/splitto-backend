# src/db.py
# Инициализация SQLAlchemy: движок, сессии, Base и явные импорты моделей.

from __future__ import annotations

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=20,
    pool_timeout=60,
    pool_recycle=1800,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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
    currency,
    group_hidden,
    group_category,
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
