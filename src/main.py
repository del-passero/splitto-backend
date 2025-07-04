from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routers.auth import router as auth_router
from src.db import engine, Base

app = FastAPI()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение маршрутов
app.include_router(auth_router, prefix="/api/auth")

# Создание таблиц в БД
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/")
def read_root():
    return {"message": "Telegram WebApp Auth API"}