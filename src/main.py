# splitto/backend/src/main.py

"""
Главная точка входа FastAPI-приложения Splitto.
Подключает все роутеры, настраивает CORS и базовые параметры API.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
load_dotenv()

from src.db import engine  # Инициализация БД

# Импорт всех роутеров (теперь все импорты на месте!)
from src.routers.auth import router as auth_router
from src.routers.users import router as users_router
from src.routers.groups import router as groups_router
from src.routers.group_members import router as group_members_router
from src.routers.transactions import router as transactions_router
from src.routers.friends import router as friends_router
from src.routers.expense_categories import router as expense_categories_router

app = FastAPI(
    title="Splitto Backend",
    description="Backend для Splitto: авторизация через Telegram, хранение пользователей, группы, транзакции и т.д.",
)

# --- Настройка CORS для работы с фронтом (Telegram Mini App обязательно!)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://splitto.app",
        "https://www.splitto.app",
        "https://splitto-backend-prod-ugraf.amvera.io"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Подключение всех роутеров с префиксами ---
app.include_router(auth_router, prefix="/api/auth", tags=["Авторизация"])
app.include_router(users_router, prefix="/api/users", tags=["Пользователи"])
app.include_router(groups_router, prefix="/api/groups", tags=["Группы"])
app.include_router(group_members_router, prefix="/api/group-members", tags=["Участники групп"])
app.include_router(transactions_router, prefix="/api/transactions", tags=["Транзакции"])
app.include_router(friends_router, prefix="/api/friends", tags=["Друзья"])
app.include_router(expense_categories_router, prefix="/api/expense-categories", tags=["Категории расходов"])

@app.get("/")
def root():
    """
    Корневой эндпоинт для проверки доступности API.
    """
    return {
        "message": "Splitto backend работает!",
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)
