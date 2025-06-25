# src/models/user.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from src.db import Base

class User(Base):
    """
    Модель пользователя, максимально адаптирована под поля Telegram API
    (и все бизнес-требования Splitto).

    Поля:
        - telegram_id: уникальный Telegram ID (используется как внешний идентификатор)
        - username: username Telegram
        - first_name: имя (Telegram)
        - last_name: фамилия (Telegram)
        - name: отображаемое имя (может быть first_name + last_name, для совместимости)
        - photo_url: url аватарки
        - language_code: язык пользователя
        - allows_write_to_pm: разрешает ли писать в ЛС (Telegram)
        - created_at: дата создания пользователя в системе
        - updated_at: дата последнего изменения профиля
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String, index=True, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    name = Column(String, index=True, nullable=True)  # можно использовать для отображения в UI
    photo_url = Column(String, nullable=True)
    language_code = Column(String(8), nullable=True)
    allows_write_to_pm = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username={self.username}, name={self.name})>"
