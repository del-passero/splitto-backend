# src/main.py
# Главная точка входа FastAPI для Splitto.
# Что изменено:
#  • Подключены новые роутеры: /api/currencies, /api/groups/{id}/categories
#  • Подготовлен (но выключен) запуск фоновой задачи авто-архива (ENV: AUTO_ARCHIVE_ENABLED=1)
#  • Остальной текущий функционал сохранён без изменений.

from __future__ import annotations

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
load_dotenv()

from src.db import engine  # инициализация БД/пула соединений

# --- Импорт существующих роутеров (как в твоём файле) ---
from src.routers.auth import router as auth_router
from src.routers.users import router as users_router
from src.routers.groups import router as groups_router
from src.routers.group_members import router as group_members_router
from src.routers.transactions import router as transactions_router
from src.routers.friends import router as friends_router
from src.routers.events import router as events_router
from src.routers.expense_categories import router as expense_categories_router

# --- НОВОЕ: наши свежие роутеры ---
from src.routers.currencies import router as currencies_router
from src.routers.group_categories import router as group_categories_router

# --- НОВОЕ: фоновая задача автоархива (включим флагом после миграций) ---
from src.jobs.auto_archive import start_auto_archive_loop

app = FastAPI(
    title="Splitto Backend",
    description="Backend для Splitto: авторизация через Telegram, пользователи, группы, транзакции и т.д.",
)

# --- CORS (оставлено как есть, дополнить домены при необходимости) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://splitto.app",
        "https://www.splitto.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Подключение роутеров ---
app.include_router(auth_router,             prefix="/api/auth",              tags=["Авторизация"])
app.include_router(users_router,            prefix="/api/users",             tags=["Пользователи"])
app.include_router(groups_router,           prefix="/api/groups",            tags=["Группы"])
app.include_router(group_members_router,    prefix="/api/group-members",     tags=["Участники групп"])
app.include_router(transactions_router,     prefix="/api/transactions",      tags=["Транзакции"])
app.include_router(friends_router,          prefix="/api/friends",           tags=["Друзья"])
app.include_router(events_router,           prefix="/api/events",            tags=["События"])
app.include_router(expense_categories_router, prefix="/api/expense-categories", tags=["Категории расходов"])

# НОВОЕ: словарь валют и категории группы
#   • Роутер валют уже имеет prefix="/currencies" → общий префикс "/api" даст /api/currencies
#   • Роутер категорий группы уже имеет prefix="/groups/{id}/categories" → общий "/api" даст нужный путь
app.include_router(currencies_router,       prefix="/api",                   tags=["Валюты"])
app.include_router(group_categories_router, prefix="/api",                   tags=["Категории группы"])

@app.get("/")
def root():
    """Простой healthcheck."""
    return {"message": "Splitto backend работает!", "docs": "/docs"}

# НОВОЕ: мягкий запуск фоновой задачи (выключено по умолчанию).
# Включится только если выставить переменную окружения AUTO_ARCHIVE_ENABLED=1.
@app.on_event("startup")
def _startup_jobs():
    if os.getenv("AUTO_ARCHIVE_ENABLED") == "1":
        # ВНИМАНИЕ: требуются миграции для полей Group (status/end_date/auto_archive/…)
        start_auto_archive_loop()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)
