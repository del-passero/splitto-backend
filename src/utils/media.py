# backend/src/utils/media.py
# -----------------------------------------------------------------------------
# Общие утилиты для работы с медиа: выбор MEDIA_ROOT, сборка публичной базы URL,
# нормализация относительных путей в абсолютные ссылки, разрешение URL в локальный
# путь внутри MEDIA_ROOT, безопасное удаление локальных файлов, а также sniff
# форматов по magic bytes (JPEG/PNG/WebP/GIF/BMP/HEIC) и PDF.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

try:
    # Для аннотаций типов; импортируем здесь, чтобы избежать циклов
    from fastapi import Request  # type: ignore
except Exception:  # pragma: no cover
    Request = object  # type: ignore


# ===== MEDIA ROOT ==============================================================

def pick_media_root() -> Path:
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


MEDIA_ROOT: Path = pick_media_root()


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


# ===== Публичная база URL и нормализация путей =================================

def public_base_url(request: "Request") -> str:
    """
    Абсолютная база для публичных ссылок (желательно HTTPS):
      1) PUBLIC_BASE_URL из окружения (рекомендуется)
      2) X-Forwarded-Proto/Host (за обратным прокси)
      3) request.url.scheme/netloc
    """
    base = os.getenv("PUBLIC_BASE_URL")
    if base:
        return base.rstrip("/")

    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).strip()
    return f"{proto}://{host}".rstrip("/")


def _extract_path(s: str) -> str:
    if s.startswith("http://") or s.startswith("https://"):
        parsed = urlparse(s)
        return parsed.path or ""
    return s


def to_abs_media_url(url: Optional[str], request: "Request") -> Optional[str]:
    """
    Превращаем относительный путь ("media/...","/media/...","group_avatars/...") в абсолютный URL.
    Абсолютные http(s) возвращаем как есть. Пустые — как есть.
    """
    if not url:
        return url
    s = str(url).strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s

    path = _extract_path(s)
    if not path.startswith("/"):
        path = "/" + path

    # Если забыли /media — добавим
    if not path.startswith("/media/"):
        if path.startswith("/group_avatars/") or path.startswith("/receipts/"):
            path = "/media" + path
        elif path.startswith("/media"):
            # например "/media" без завершающего слэша
            if path != "/media":
                path = "/media/" + path[len("/media/"):]
        else:
            path = "/media" + path

    base = public_base_url(request)
    return f"{base}{path}"


# ===== URL -> локальный путь в MEDIA_ROOT =====================================

def url_to_media_local_path(
    url: Optional[str],
    *,
    allowed_subdirs: Optional[Tuple[str, ...]] = None
) -> Optional[Path]:
    """
    Преобразует входной url/путь в локальный путь внутри MEDIA_ROOT.
    Если задан allowed_subdirs — путь должен начинаться с одного из них
    (например, ("group_avatars",) для удаления только аватаров).
    """
    if not url:
        return None

    raw = _extract_path(str(url).strip())
    if not raw:
        return None
    if not raw.startswith("/"):
        raw = "/" + raw

    # Ожидаемые варианты: "/media/<rel>", "/group_avatars/<file>", "/receipts/<file>"
    if "/media/" in raw:
        rel = raw.split("/media/", 1)[1]
    elif raw.startswith("/group_avatars/"):
        rel = raw[1:]
    elif raw.startswith("/receipts/"):
        rel = raw[1:]
    else:
        return None

    if allowed_subdirs:
        ok = any(rel.startswith(prefix.rstrip("/") + "/") or rel == prefix.rstrip("/")
                 for prefix in allowed_subdirs)
        if not ok:
            return None

    local = (MEDIA_ROOT / rel)
    try:
        local_resolved = local.resolve()
        media_resolved = MEDIA_ROOT.resolve()
        _ = local_resolved.relative_to(media_resolved)  # гарантия, что внутри MEDIA_ROOT
    except Exception:
        return None
    return local


def delete_if_local(url: Optional[str], *, allowed_subdirs: Optional[Tuple[str, ...]] = None) -> bool:
    """
    Удаляет файл из ФС, если URL указывает на файл в MEDIA_ROOT (+ опциональный фильтр поддиректорий).
    Возвращает True, если удалили; False — если нечего/не удалось.
    """
    try:
        p = url_to_media_local_path(url, allowed_subdirs=allowed_subdirs)
        if p and p.exists():
            p.unlink()
            return True
        return False
    except Exception:
        return False


# ===== Sniff / magic bytes =====================================================

def is_pdf_bytes(head: bytes) -> bool:
    """PDF начинается с '%PDF-'."""
    return head.startswith(b"%PDF-")


def sniff_image_format(head: bytes) -> Optional[str]:
    """
    Возвращает код формата по magic bytes: 'jpeg', 'png', 'gif', 'webp', 'bmp', 'heic'.
    Если не похоже на изображение — None.
    """
    if len(head) < 12:
        head = head + b"\x00" * (12 - len(head))

    # JPEG: FF D8 FF
    if head[:3] == b"\xFF\xD8\xFF":
        return "jpeg"
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    # GIF: GIF87a / GIF89a
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    # WEBP: "RIFF"...."WEBP"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    # BMP: "BM"
    if head[:2] == b"BM":
        return "bmp"
    # HEIF/HEIC (ISO BMFF): 'ftypheic' / 'ftypheif' / 'ftypmif1' / 'ftypmsf1' / 'ftyphevc'
    if b"ftypheic" in head[:64] or b"ftypheif" in head[:64] or b"ftypmif1" in head[:64] or b"ftypmsf1" in head[:64] or b"ftyphevc" in head[:64]:
        return "heic"
    return None


def ext_for_image(fmt: str) -> str:
    return {
        "jpeg": ".jpg",
        "png": ".png",
        "gif": ".gif",
        "webp": ".webp",
        "bmp":  ".bmp",
        "heic": ".heic",
        "heif": ".heif",
    }.get(fmt, ".bin")
