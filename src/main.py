# src/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
load_dotenv()

from src.db import engine  # или как у тебя инициализация БД

# Импорт роутеров
from src.routers.auth import router as auth_router
# ... другие роутеры

app = FastAPI(
    title="Splitto Backend",
    description="Splitwise-like Telegram WebApp backend.",
)

# CORS (для разработки localhost + боевой домен)
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

# Подключаем роутеры
app.include_router(auth_router, prefix="/api/auth", tags=["Авторизация"])
# ... остальные роутеры

@app.get("/")
def root():
    return {"message": "Splitto backend работает!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
