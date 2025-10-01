# backend/src/routers/upload.py
# Эндпоинты загрузки изображений:
#  • Аватары групп -> <MEDIA_ROOT>/group_avatars/YYYY/MM/<random>.<ext>
#  • Чеки (ТОЛЬКО фото) -> <MEDIA_ROOT>/receipts/YYYY/MM/<random>.<ext>
# Отдаются по:
#  • /media/group_avatars/YYYY/MM/<name>
#  • /media/receipts/YYYY/MM/<name>

from __future__ import annotations

import os
import secrets
import mimetypes
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Depends

from src.utils.telegram_dep import get_current_telegram_user
from src.utils.media import (
    MEDIA_ROOT,
    ensure_dir,
    public_base_url,
    sniff_image_format,   # распознаём формат по magic bytes
    ext_for_image,        # подбираем расширение по распознанному формату
    is_pdf_bytes,         # используем, чтобы вернуть понятную ошибку
)

router = APIRouter()

# ===== Настройки лимитов / директории ========================================

# общий лимит размера (можно переопределить env-переменной MAX_UPLOAD_MB)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
CHUNK_SIZE = 1024 * 1024  # 1MB

# Базовые директории медиа
GROUP_DIR_ROOT = ensure_dir(MEDIA_ROOT / "group_avatars")
RECEIPTS_DIR_ROOT = ensure_dir(MEDIA_ROOT / "receipts")

# Разрешённые расширения для подстраховки по имени
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}


def _today_subdir() -> Path:
    """YYYY/MM — удобно группировать помесячно, а не захламлять корень."""
    now = datetime.utcnow()
    return Path(f"{now:%Y}/{now:%m}")


def _write_streamed(file: UploadFile, dst: Path) -> None:
    """Записываем UploadFile в dst, контролируя общий размер и очищая частично записанное при ошибке."""
    total = 0
    try:
        with dst.open("wb") as f:
            # читаем head для сохранения того, что уже прочли у вызывающего кода
            head = getattr(file, "_head_bytes", b"")
            if head:
                f.write(head)
                total += len(head)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File too large (>{MAX_UPLOAD_MB} MB)")
            while True:
                chunk = file.read(CHUNK_SIZE)
                if hasattr(chunk, "__await__"):  # если это async UploadFile.read в разных серверах
                    chunk = yield from chunk.__await__()
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


async def _read_head(file: UploadFile, size: int = 64 * 1024) -> bytes:
    head = await file.read(size)
    # Сохраняем head, чтобы _write_streamed дописал его первым
    setattr(file, "_head_bytes", head)
    return head


def _pick_image_ext(head: bytes, ctype: str, name_ext: str) -> str:
    """Определяем расширение для изображения: по magic, затем по content-type, затем по имени."""
    fmt = sniff_image_format(head)
    if not fmt:
        if is_pdf_bytes(head):
            raise HTTPException(status_code=415, detail="PDF не поддерживается. Прикрепляйте фото.")
        raise HTTPException(status_code=415, detail="Unsupported image format")
    magic_ext = ext_for_image(fmt)
    guessed_ext = mimetypes.guess_extension(ctype) or ""
    # приоритет magic -> guessed -> name -> .jpg по умолчанию
    ext = magic_ext or guessed_ext or (name_ext if name_ext in _IMAGE_EXTS else "") or ".jpg"
    return ext


def _public_url(base: str, media_path: Path) -> str:
    # media_path относительный к MEDIA_ROOT (например: group_avatars/2025/10/abcd.jpg)
    return f"{base}/media/{media_path.as_posix()}"


# ===== Маршруты ===============================================================

# --- Аватары групп: ТОЛЬКО изображения ---------------------------------------

@router.post("/upload/image")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    current_user = Depends(get_current_telegram_user),
):
    ctype = (file.content_type or "").lower()
    name_ext = (os.path.splitext(file.filename or "")[1].lower() or "")

    head = await _read_head(file)

    # Определяем расширение строго как изображение (PDF отвергаем)
    ext = _pick_image_ext(head, ctype, name_ext)

    # Поддиректория по дате
    subdir = _today_subdir()
    dst_dir = ensure_dir(GROUP_DIR_ROOT / subdir)

    name = f"{secrets.token_hex(16)}{ext}"
    dst_rel = Path("group_avatars") / subdir / name
    dst_abs = dst_dir / name

    # Запись
    await _write_streamed(file, dst_abs)

    base = public_base_url(request)
    return {"url": _public_url(base, dst_rel)}


# --- Чеки транзакций: ТОЛЬКО изображения -------------------------------------

@router.post("/upload/receipt")
async def upload_receipt(
    request: Request,
    file: UploadFile = File(...),
    current_user = Depends(get_current_telegram_user),
):
    """
    Принимает ТОЛЬКО image/* (PDF запрещён).
    Сохраняет файл и возвращает абсолютный URL вида:
      https://.../media/receipts/YYYY/MM/<random>.<ext>
    """
    ctype = (file.content_type or "").lower()
    name_ext = (os.path.splitext(file.filename or "")[1].lower() or "")

    head = await _read_head(file)

    # Разрешаем только изображение. Если это PDF — шлём понятную 415.
    ext = _pick_image_ext(head, ctype, name_ext)

    # Поддиректория по дате
    subdir = _today_subdir()
    dst_dir = ensure_dir(RECEIPTS_DIR_ROOT / subdir)

    name = f"{secrets.token_hex(16)}{ext}"
    dst_rel = Path("receipts") / subdir / name
    dst_abs = dst_dir / name

    await _write_streamed(file, dst_abs)

    base = public_base_url(request)
    return {"url": _public_url(base, dst_rel)}
