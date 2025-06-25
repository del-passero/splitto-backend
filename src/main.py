# src/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.db import engine  # Абсолютный импорт

# Импортируем все роутеры (добавлены новые/расширенные)
from src.routers.users import router as users_router
from src.routers.groups import router as groups_router
from src.routers.group_members import router as group_members_router
from src.routers.friends import router as friends_router
from src.routers.expense_categories import router as expense_categories_router
from src.routers.transactions import router as transactions_router

# !!! Не подключаем Base.metadata.create_all(bind=engine) — только alembic занимается созданием таблиц!

app = FastAPI(
    title="Splitto Backend",
    description="Splitwise-like Telegram WebApp backend. Все API реализованы с учётом поддержки Telegram-style UI и расширенной логики.",
)

# ========================
# Настройка CORS
# ========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # На production ограничить домены!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================
# Подключение роутеров
# ========================
app.include_router(users_router, prefix="/users", tags=["Пользователи"])
app.include_router(groups_router, prefix="/groups", tags=["Группы"])
app.include_router(group_members_router, prefix="/group_members", tags=["Участники группы"])
app.include_router(friends_router, prefix="/friends", tags=["Друзья и контакты"])
app.include_router(expense_categories_router, prefix="/expense-categories", tags=["Категории расходов"])
app.include_router(transactions_router, prefix="/transactions", tags=["Транзакции"])

@app.get("/")
def root():
    """
    Корневой эндпоинт для проверки доступности API.
    """
    return {"message": "Splitto backend работает! (PostgreSQL + группы + друзья + балансы + settle-up)"}
