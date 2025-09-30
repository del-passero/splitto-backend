# backend/src/routers/upload.py
# Эндпоинт загрузки изображений (аватары групп) + чеков (image/pdf) в персистентное хранилище.
# Файлы сохраняются в <MEDIA_ROOT>/group_avatars и <MEDIA_ROOT>/receipts
# и отдаются по /media/group_avatars/<name> и /media/receipts/<name>.

from __future__ import annotations

import os
import secrets
import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Depends

from src.utils.telegram_dep import get_current_telegram_user
from src.utils.media import (
    MEDIA_ROOT,
    ensure_dir,
    public_base_url,
    sniff_image_format,
    is_pdf_bytes,
    ext_for_image,
)

router = APIRouter()

# ===== Настройки лимитов / директории ========================================

# общий лимит размера (можно переопределить env-переменной MAX_UPLOAD_MB)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
CHUNK_SIZE = 1024 * 1024  # 1MB

# --- Поддиректории ------------------------------------------------------------
GROUP_DIR = ensure_dir(MEDIA_ROOT / "group_avatars")
RECEIPTS_DIR = ensure_dir(MEDIA_ROOT / "receipts")

# --- Поддержка PDF content-types ---------------------------------------------
_PDF_CTYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/acrobat",
    "applications/vnd.pdf",
    "text/pdf",
    "text/x-pdf",
}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}

# ===== Маршруты ===============================================================

# --- Аватары групп ------------------------------------------------------------

@router.post("/upload/image")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    current_user = Depends(get_current_telegram_user),  # авторизация обязательна
):
    # Базовая проверка content-type (для UX), но доверяем только magic bytes
    ctype = (file.content_type or "").lower()
    if not ctype.startswith("image/"):
        # не блокируем только по заголовку — проверим magic ниже
        pass

    # Считываем head для sniff'а
    head = await file.read(64 * 1024)
    fmt = sniff_image_format(head)
    if not fmt:
        if is_pdf_bytes(head):
            raise HTTPException(status_code=415, detail="PDF не поддерживается для /upload/image")
        raise HTTPException(status_code=415, detail="Unsupported image format")

    # Имя файла/расширение
    name_ext = (os.path.splitext(file.filename or "")[1].lower() or "")
    magic_ext = ext_for_image(fmt)
    guessed_ext = mimetypes.guess_extension(ctype) or ""
    ext = magic_ext or guessed_ext or name_ext or ".bin"
    name = f"{secrets.token_hex(16)}{ext}"
    dst = GROUP_DIR / name

    # Пишем head + остаток, контролируя общий размер
    total = 0
    try:
        with dst.open("wb") as f:
            if head:
                f.write(head)
                total += len(head)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File too large (>{MAX_UPLOAD_MB} MB)")
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File too large (>{MAX_UPLOAD_MB} MB)")
                f.write(chunk)
    except HTTPException:
        try:
            if dst.exists():
                dst.unlink(missing_ok=True)  # удалим частично записанный файл
        except Exception:
            pass
        raise
    finally:
        await file.close()

    base = public_base_url(request)
    return {"url": f"{base}/media/group_avatars/{name}"}


# --- Чеки транзакций ----------------------------------------------------------

@router.post("/upload/receipt")
async def upload_receipt(
    request: Request,
    file: UploadFile = File(...),
    current_user = Depends(get_current_telegram_user),  # авторизация обязательна
):
    """
    Принимает image/* или application/pdf (включая частые вариации).
    Сохраняет файл и возвращает абсолютный URL вида https://.../media/receipts/<random>.<ext>
    """
    ctype = (file.content_type or "").lower()
    filename = (file.filename or "")
    name_ext = os.path.splitext(filename)[1].lower()

    # Считываем head для надёжной идентификации
    head = await file.read(64 * 1024)

    # Определяем тип по magic; затем сверяем с content-type/расширением
    is_pdf_magic = is_pdf_bytes(head)
    img_fmt = sniff_image_format(head)

    # Бизнес-правило: разрешаем либо PDF, либо изображение
    is_pdf = is_pdf_magic or (ctype in _PDF_CTYPES) or (name_ext == ".pdf")
    is_image = bool(img_fmt) or ctype.startswith("image/") or (name_ext in _IMAGE_EXTS)

    if not (is_pdf or is_image):
        raise HTTPException(
            status_code=415,
            detail=f"Only image/* or application/pdf allowed (got content-type='{ctype}', filename='{filename}')"
        )

    # Расширение
    if is_pdf:
        ext = ".pdf"
    else:
        ext = ext_for_image(img_fmt or "jpeg")

    name = f"{secrets.token_hex(16)}{ext}"
    dst = RECEIPTS_DIR / name

    total = 0
    try:
        with dst.open("wb") as f:
            if head:
                f.write(head)
                total += len(head)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File too large (>{MAX_UPLOAD_MB} MB)")
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File too large (>{MAX_UPLOAD_MB} MB)")
                f.write(chunk)
    except HTTPException:
        try:
            if dst.exists():
                dst.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    finally:
        await file.close()

    base = public_base_url(request)
    return {"url": f"{base}/media/receipts/{name}"}
