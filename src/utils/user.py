# src/utils/user.py

def get_display_name(first_name: str = "", last_name: str = "", username: str = "", telegram_id: int = None) -> str:
    """
    Формирует отображаемое имя пользователя:
    1. Если есть first_name и last_name — склеивает через пробел.
    2. Если есть только first_name — его.
    3. Если нет имени — username.
    4. Если и username нет — Telegram ID.
    """
    name = " ".join(filter(None, [first_name, last_name]))
    if name.strip():
        return name.strip()
    if username:
        return username
    if telegram_id is not None:
        return str(telegram_id)
    return ""
