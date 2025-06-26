from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

config = context.config

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from src.db import Base

# Конфигурируем логирование (ВЫЗОВ fileConfig ДОЛЖЕН БЫТЬ ПЕРЕД set_main_option!)
fileConfig(config.config_file_name)

# Только теперь подставляем url из env!
url = os.environ.get("DATABASE_URL")
if url:
    config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
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
