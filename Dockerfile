# Используем официальный Python-образ (лучше брать 3.10 или выше)
FROM python:3.10-slim

# 1. Переменные окружения (чтобы Python не кешировал pyc и выводил логи сразу)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 2. Рабочая директория внутри контейнера
WORKDIR /app

# 3. Копируем только requirements.txt и alembic.ini — чтобы кэшировался pip install
COPY requirements.txt .
COPY alembic.ini .
COPY ./alembic ./alembic

# 4. Устанавливаем зависимости (если нужно — добавь gcc, libpq-dev и т.д.)
RUN pip install --upgrade pip && pip install -r requirements.txt

# 5. Копируем исходный код приложения (src/ и всё, что нужно для запуска)
COPY ./src ./src

# 6. (Опционально) Копируем другие скрипты/файлы, если нужно

# 7. Открываем нужный порт (FastAPI по умолчанию 8000)
EXPOSE 8000

# 8. Команда запуска
# Вариант с uvicorn и автоперезапуском (для dev). Для production лучше gunicorn+uvicorn
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
