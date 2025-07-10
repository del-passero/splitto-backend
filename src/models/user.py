# src/models/user.py

from sqlalchemy import Column, BigInteger, Integer, String, Boolean, DateTime, func
from src.db import Base

class User(Base):
    """
    Модель пользователя, максимально адаптирована под поля Telegram API
    и бизнес-требования Splitto.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String, index=True, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    name = Column(String, index=True, nullable=True)  # Отображаемое имя
    photo_url = Column(String, nullable=True)
    language_code = Column(String(8), nullable=True)
    allows_write_to_pm = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # --- Новые поля для PRO-статуса и рефералов ---
    is_pro = Column(Boolean, default=False, nullable=False, comment="Является ли пользователь PRO")
    invited_friends_count = Column(Integer, default=0, nullable=False, comment="Сколько друзей добавлено по инвайт-ссылке")

    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username={self.username}, name={self.name}, is_pro={self.is_pro}, invited_friends_count={self.invited_friends_count})>"
