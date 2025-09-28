# src/routers/upload.py
# Эндпоинт загрузки изображений (аватары групп) + чеков (image/pdf) в персистентное хранилище.
# Файлы сохраняются в <MEDIA_ROOT>/group_avatars и <MEDIA_ROOT>/receipts
# и отдаются по /media/group_avatars/<name> и /media/receipts/<name>.

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, HTTPException, Request
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

def _public_base_url(request: Request) -> str:
    """
    Абсолютная база для публичных ссылок (HTTPS):
      1) PUBLIC_BASE_URL из окружения (рекомендуется)
      2) X-Forwarded-Proto/Host (за обратным прокси)
      3) request.url.scheme/netloc
    """
    base = os.getenv("PUBLIC_BASE_URL")
    if base:
        return base.rstrip("/")

    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")

# --- Аватары групп ------------------------------------------------------------
GROUP_DIR = MEDIA_ROOT / "group_avatars"
GROUP_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_PREFIXES = ("image/",)  # для /upload/image принимаем только image/*

@router.post("/upload/image")
async def upload_image(file: UploadFile = File(...), request: Request = None):
    # Проверка content-type
    ctype = (file.content_type or "").lower()
    if not any(ctype.startswith(p) for p in ALLOWED_PREFIXES):
        raise HTTPException(status_code=415, detail="Only image/* allowed")

    # Генерация имени, определяем расширение (сFallbackом по исходному имени)
    guessed_ext = mimetypes.guess_extension(ctype) or ""
    name_ext = (os.path.splitext(file.filename or "")[1].lower() or "")
    ext = guessed_ext or name_ext or ".bin"

    name = f"{secrets.token_hex(16)}{ext}"
    dst = GROUP_DIR / name

    try:
        with dst.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        await file.close()

    # Публичный абсолютный URL (по HTTPS при корректной базе)
    base = _public_base_url(request)
    return {"url": f"{base}/media/group_avatars/{name}"}

# --- Чеки транзакций ----------------------------------------------------------
RECEIPTS_DIR = MEDIA_ROOT / "receipts"
RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

# Поддерживаем популярные варианты content-type для PDF
_PDF_CTYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/acrobat",
    "applications/vnd.pdf",
    "text/pdf",
    "text/x-pdf",
}
# Набор распространённых расширений изображений (для fallback по имени файла)
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}

@router.post("/upload/receipt")
async def upload_receipt(file: UploadFile = File(...), request: Request = None):
    """
    Принимает image/* или application/pdf (включая частые вариации).
    Сохраняет файл и возвращает абсолютный URL вида https://.../media/receipts/<random>.<ext>
    """
    ctype = (file.content_type or "").lower()
    filename = (file.filename or "")
    name_ext = os.path.splitext(filename)[1].lower()

    # Разрешаем:
    #  - image по content-type или по расширению имени файла,
    #  - pdf по известным content-type, по расширению .pdf, либо по octet-stream + .pdf
    is_image = ctype.startswith("image/") or name_ext in _IMAGE_EXTS
    is_pdf = (ctype in _PDF_CTYPES) or (name_ext == ".pdf") or (
        ctype == "application/octet-stream" and name_ext == ".pdf"
    )

    if not (is_image or is_pdf):
        raise HTTPException(
            status_code=415,
            detail=f"Only image/* or application/pdf allowed (got content-type='{ctype}', filename='{filename}')"
        )

    # Для PDF — всегда .pdf; для картинок — по mimetypes либо по расширению
    if is_pdf:
        ext = ".pdf"
    else:
        guessed_ext = mimetypes.guess_extension(ctype) or ""
        ext = guessed_ext or name_ext or ".bin"

    name = f"{secrets.token_hex(16)}{ext}"
    dst = RECEIPTS_DIR / name

    try:
        with dst.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        await file.close()

    base = _public_base_url(request)
    return {"url": f"{base}/media/receipts/{name}"}
