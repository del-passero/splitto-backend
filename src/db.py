import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL") 

# ВАЖНО: Добавляем параметры пула!
engine = create_engine(
    DATABASE_URL,
    pool_size=20,        # сколько соединений держать "в пуле"
    max_overflow=20,     # сколько "экстренных" поверх пула можно открыть
    pool_timeout=60,     # сколько ждать соединения (сек.)
    pool_recycle=1800,   # сколько жить соединению до автоматического закрытия (сек.)
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
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
