from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
load_dotenv()

from src.db import engine  # инициализация БД (если есть)
# Импорт роутеров:
from src.routers.auth import router as auth_router
from src.routers.users import router as users_router
# ... другие роутеры по мере необходимости

app = FastAPI(
    title="Splitto Backend",
    description="Backend для Splitto: авторизация через Telegram, хранение пользователей и т.д.",
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

# --- Подключение роутеров ---
app.include_router(auth_router, prefix="/api/auth", tags=["Авторизация"])
app.include_router(users_router, prefix="/api/users", tags=["Пользователи"])
# ... остальные include_router

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
