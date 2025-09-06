# src/services/group_invite_token.py
from __future__ import annotations
import os
import hmac
import base64
import hashlib
from typing import Tuple

# Префикс, по которому фронт отличает тип токена
TOKEN_PREFIX = "GINV_"

def _get_secret() -> bytes:
    # Можно завести отдельный секрет GROUP_INVITE_SECRET, иначе — fallback на TELEGRAM_BOT_TOKEN
    secret = os.environ.get("GROUP_INVITE_SECRET") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not secret:
        raise RuntimeError("GROUP_INVITE_SECRET or TELEGRAM_BOT_TOKEN must be set")
    return secret.encode("utf-8")

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

def _unb64url(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

def create_group_invite_token(group_id: int, inviter_id: int) -> str:
    """
    Формат: GINV_<gid>_<uid>_<sig>
    где sig = base64url( HMAC(secret, f"{gid}:{uid}") )
    """
    secret = _get_secret()
    base = f"{int(group_id)}:{int(inviter_id)}".encode("utf-8")
    sig = hmac.new(secret, base, hashlib.sha256).digest()
    token = f"{TOKEN_PREFIX}{group_id}_{inviter_id}_{_b64url(sig)}"
    return token

def parse_and_validate_token(token: str) -> Tuple[int, int]:
    """
    Возвращает (group_id, inviter_id) или бросает ValueError.
    """
    if not token or not token.startswith(TOKEN_PREFIX):
        raise ValueError("bad_prefix")
    try:
        _, gid, uid, sig = token.split("_", 3)
        gid_i = int(gid)
        uid_i = int(uid)
        secret = _get_secret()
        base = f"{gid_i}:{uid_i}".encode("utf-8")
        expected = hmac.new(secret, base, hashlib.sha256).digest()
        got = _unb64url(sig)
        if not hmac.compare_digest(expected, got):
            raise ValueError("bad_signature")
        return gid_i, uid_i
    except Exception as e:
        raise ValueError(str(e))
