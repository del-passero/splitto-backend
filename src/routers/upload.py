# src/routers/upload.py
# Эндпоинт загрузки изображений (аватары групп) + чеков (image/pdf) в персистентное хранилище.
# Файлы сохраняются в <MEDIA_ROOT>/group_avatars и <MEDIA_ROOT>/receipts
# и отдаются по /media/group_avatars/<name> и /media/receipts/<name>.

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
import os
import secrets
import shutil
import mimetypes

router = APIRouter()

def _pick_media_root() -> Path:
    """
    Выбираем корень хранения:
      1) SPLITTO_MEDIA_ROOT (в проде укажи /data/uploads)
      2) иначе пробуем /data/uploads
      3) если нет прав/папки — локальный ./var/uploads
    """
    primary = Path(os.getenv("SPLITTO_MEDIA_ROOT") or "/data/uploads")
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        fallback = Path(os.getenv("SPLITTO_MEDIA_FALLBACK") or os.path.abspath("./var/uploads"))
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

MEDIA_ROOT = _pick_media_root()

# --- Аватары групп ------------------------------------------------------------
GROUP_DIR = MEDIA_ROOT / "group_avatars"
GROUP_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_PREFIXES = ("image/",)  # для /upload/image принимаем только image/*

@router.post("/upload/image")
async def upload_image(file: UploadFile = File(...)):
    # Проверка content-type
    ctype = (file.content_type or "").lower()
    if not any(ctype.startswith(p) for p in ALLOWED_PREFIXES):
        raise HTTPException(status_code=415, detail="Only image/* allowed")

    # Генерация имени, определяем расширение
    ext = mimetypes.guess_extension(ctype) or ".bin"
    name = f"{secrets.token_hex(16)}{ext}"
    dst = GROUP_DIR / name

    try:
        with dst.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        await file.close()

    # Публичный URL — будет отдаваться через app.mount("/media", ...)
    return {"url": f"/media/group_avatars/{name}"}

# --- Чеки транзакций ----------------------------------------------------------
RECEIPTS_DIR = MEDIA_ROOT / "receipts"
RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/upload/receipt")
async def upload_receipt(file: UploadFile = File(...)):
    """
    Принимает image/* или application/pdf.
    Сохраняет файл в /media/receipts/<random>.<ext> и возвращает относительный URL.
    """
    ctype = (file.content_type or "").lower()
    is_image = ctype.startswith("image/")
    is_pdf = (ctype == "application/pdf")

    if not (is_image or is_pdf):
        raise HTTPException(status_code=415, detail="Only image/* or application/pdf allowed")

    # Для PDF расширение фиксируем .pdf, для картинок — по mimetypes
    ext = ".pdf" if is_pdf else (mimetypes.guess_extension(ctype) or ".bin")
    name = f"{secrets.token_hex(16)}{ext}"
    dst = RECEIPTS_DIR / name

    try:
        with dst.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        await file.close()

    return {"url": f"/media/receipts/{name}"}
