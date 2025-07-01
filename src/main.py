# src/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
load_dotenv()

from src.db import engine

# Импортируем все роутеры
from src.routers.users import router as users_router
from src.routers.groups import router as groups_router
from src.routers.group_members import router as group_members_router
from src.routers.friends import router as friends_router
from src.routers.expense_categories import router as expense_categories_router
from src.routers.transactions import router as transactions_router
from src.routers.auth import router as auth_router

app = FastAPI(
    title="Splitto Backend",
    description="Splitwise-like Telegram WebApp backend. Все API реализованы с учётом поддержки Telegram-style UI и расширенной логики.",
)

# --- Настройка CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://splitto.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Подключение роутеров ---
app.include_router(auth_router, prefix="/api/auth", tags=["Авторизация"])
app.include_router(users_router, prefix="/api/users", tags=["Пользователи"])
app.include_router(groups_router, prefix="/api/groups", tags=["Группы"])
app.include_router(group_members_router, prefix="/api/group_members", tags=["Участники группы"])
app.include_router(friends_router, prefix="/api/friends", tags=["Друзья и контакты"])
app.include_router(expense_categories_router, prefix="/api/expense-categories", tags=["Категории расходов"])
app.include_router(transactions_router, prefix="/api/transactions", tags=["Транзакции"])


@app.get("/")
def root():
    """
    Корневой эндпоинт для проверки доступности API.
    """
    return {
        "message": "Splitto backend работает! (PostgreSQL + группы + друзья + балансы + settle-up)",
        "docs": "/docs",
        "users_me_example": "/users/me (нужно передавать initData!)"
    }
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)
