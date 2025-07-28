# alembic/env.py

import sys
import os

from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from alembic import context
from dotenv import load_dotenv

# --- Загрузка переменных окружения из .env ---
load_dotenv()

# --- Добавляем src в sys.path для корректного импорта моделей ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

# --- Импортируем Base и ВСЕ МОДЕЛИ ---
from src.db import Base
from src.models import (
    user,
    friend,
    friend_invite,
    invite_usage,
    event,
    expense_category,
    group,
    group_member,
    transaction,
    transaction_share,
    # если будут новые модели — обязательно допиши сюда!
)

# --- Конфигурируем Alembic ---
config = context.config

# --- Логирование Alembic ---
fileConfig(config.config_file_name)

# --- Target metadata для Alembic (все твои модели тут!) ---
target_metadata = Base.metadata

# --- Берём строку подключения к БД (DATABASE_URL) ---
db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL is not set!")

def run_migrations_offline():
    context.configure(
        url=db_url,  # ← напрямую сюда!
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = create_engine(
        db_url,  # ← напрямую сюда!
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
