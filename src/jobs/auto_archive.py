# src/jobs/auto_archive.py
# АВТОАРХИВ ГРУПП ПО end_date (РАЗ В СУТКИ)
# -----------------------------------------------------------------------------
# Что делает этот модуль:
#   • Находит группы, у которых:
#       - auto_archive = true,
#       - end_date < сегодня (уже прошла),
#       - status = 'active',
#       - deleted_at IS NULL,
#     и если в группе НЕТ долгов — переводит группу в archived и проставляет archived_at = now().
#
# Как запускать:
#   Вариант А) Одноразовый прогон вручную (например, из команды или раннера CI/CD):
#       >>> from src.jobs.auto_archive import auto_archive_once
#       >>> auto_archive_once()
#
#   Вариант Б) Бесконечная фоновая задача (раз в сутки), стартующая на событии FastAPI startup:
#       >>> from src.jobs.auto_archive import start_auto_archive_loop
#       В main.py в @app.on_event("startup"):
#           start_auto_archive_loop()
#
#   По нашему плану мы подключим вызов в main.py ОДНИМ касанием в самом конце (после миграций).
#
# Важно:
#   • Код опирается на новые поля Group: status/archived_at/deleted_at/end_date/auto_archive.
#   • Не запускайте до применения миграций — иначе будут ошибки "column does not exist".

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import SessionLocal  # создаёт новую сессию БД
from src.models.group import Group, GroupStatus
from src.utils.groups import has_group_debts  # используем ОДНУ истину расчёта долгов

log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Текущее время в UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


def _today_utc() -> date:
    """Текущая дата по UTC (без времени)."""
    return _utc_now().date()


def _find_candidates(db: Session) -> list[Group]:
    """
    Ищем группы-кандидаты на автоархив:
      • auto_archive = true
      • end_date < today (UTC)
      • status = 'active'
      • deleted_at IS NULL
    ВАРИАНТЫ:
      - Архивируем только те, где нет долгов (проверяем дальше, по одной группе).
    """
    today = _today_utc()
    stmt = (
        select(Group)
        .where(
            Group.deleted_at.is_(None),
            Group.status == GroupStatus.active,
            Group.auto_archive.is_(True),
            Group.end_date.is_not(None),
            Group.end_date < today,
        )
        .order_by(Group.end_date.asc(), Group.id.asc())
    )
    return list(db.scalars(stmt).all())


def _archive_group(db: Session, group: Group) -> bool:
    """
    Переводит конкретную группу в archived, если нет долгов.
    Возвращает True, если группа переведена в архив; False, если пропущена (например, есть долги).
    """
    # Ещё раз проверим, что она всё ещё активна (могли поменять статус конкурентно)
    if group.status != GroupStatus.active or group.deleted_at is not None:
        return False

    # Проверяем наличие долгов через общую функцию
    try:
        if has_group_debts(db, group.id):
            return False
    except Exception as e:
        # Если расчёт долга упал — логируем и не архивируем эту группу
        log.exception("auto-archive: failed to calculate debts for group %s: %s", group.id, e)
        return False

    # Архивируем
    group.status = GroupStatus.archived
    group.archived_at = _utc_now()
    return True


def auto_archive_once() -> dict:
    """
    Одноразовый прогон задачи:
      - открывает новую сессию,
      - ищет кандидатов,
      - для каждого пытается перевести в архив (если нет долгов),
      - коммитит все изменения пачкой,
      - возвращает сводку.
    """
    with SessionLocal() as db:
        candidates = _find_candidates(db)
        archived_ids: list[int] = []
        skipped_ids: list[int] = []

        for g in candidates:
            ok = _archive_group(db, g)
            (archived_ids if ok else skipped_ids).append(g.id)

        # Коммит одним разом — дешевле, чем каждый раз
        db.commit()

    summary = {
        "archived_count": len(archived_ids),
        "archived_ids": archived_ids,
        "skipped_count": len(skipped_ids),
        "skipped_ids": skipped_ids,
    }
    log.info("auto-archive summary: %s", summary)
    return summary


async def _sleep_until_next_run(hour: int = 3, minute: int = 0) -> None:
    """
    Спит до следующего «окна» запуска.
    По умолчанию — следующая 03:00 (по времени сервера). Если время уже прошло — до завтра.
    """
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    await asyncio.sleep((target - now).total_seconds())


async def _loop_daily() -> None:
    """
    Бесконечный цикл:
      - ждём до следующего запуска (по умолчанию 03:00),
      - запускаем auto_archive_once(),
      - в случае исключений — логируем и продолжаем,
      - повторяем.
    """
    while True:
        try:
            await _sleep_until_next_run(hour=3, minute=0)
            auto_archive_once()
        except Exception:
            log.exception("auto-archive loop iteration failed")


def start_auto_archive_loop() -> None:
    """
    Запускает фоновую задачу в текущем asyncio-цикле.
    Вызвать из FastAPI @app.on_event('startup') (мы добавим в main.py одним касанием).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Нет активного event loop — ничего не делаем (например, при однократном вызове скрипта)
        return
    loop.create_task(_loop_daily())
