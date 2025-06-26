from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

# Получаем config из Alembic context (делать это сразу после импорта context)
config = context.config

# Добавляем src/ в sys.path для корректного импорта моделей
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

# Импортируем Base (метаданные моделей)
from src.db import Base

# Устанавливаем строку подключения к БД из переменной окружения (если есть)
url = os.environ.get("DATABASE_URL")
if url:
    config.set_main_option("sqlalchemy.url", url)

# Конфигурируем логирование из файла alembic.ini
fileConfig(config.config_file_name)

# Метаданные моделей для Alembic (для автогенерации миграций)
target_metadata = Base.metadata

def run_migrations_offline():
    """Запуск миграций в оффлайн-режиме (генерация SQL-файла)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Запуск миграций в онлайн-режиме (прямое применение к БД)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
