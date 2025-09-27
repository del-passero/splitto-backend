# src/services/group_invite_token.py

from __future__ import annotations

import os
import hmac
import base64
import hashlib
from typing import Tuple

_PREFIX = "GINV"

def _secret() -> bytes:
    s = os.environ.get("GROUP_INVITE_SECRET") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not s:
        raise RuntimeError("GROUP_INVITE_SECRET or TELEGRAM_BOT_TOKEN is not set")
    return s.encode("utf-8")

def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")

def _b64url_fixpad(s: str) -> str:
    rem = len(s) % 4
    return s + ("=" * ((4 - rem) % 4))

def create_group_invite_token(group_id: int, inviter_id: int) -> str:
    if not isinstance(group_id, int) or not isinstance(inviter_id, int):
        raise ValueError("bad_args")
    payload = f"{group_id}:{inviter_id}".encode("utf-8")
    mac = hmac.new(_secret(), payload, hashlib.sha256).digest()
    sig = _b64url_encode(mac)
    return f"{_PREFIX}_{group_id}_{inviter_id}_{sig}"

def parse_and_validate_token(token: str) -> Tuple[int, int]:
    if not token:
        raise ValueError("bad_token")

    t = token.strip()
    low = t.lower()
    for pref in ("join:", "g:", "token="):
        if low.startswith(pref):
            t = t[len(pref):]
            low = t.lower()

    if not t.startswith(_PREFIX + "_"):
        raise ValueError("bad_prefix")

    parts = t.split("_", 3)
    if len(parts) != 4:
        raise ValueError("bad_format")

    _, gid_str, uid_str, sig = parts
    try:
        gid = int(gid_str)
        uid = int(uid_str)
    except Exception:
        raise ValueError("bad_format")

    payload = f"{gid}:{uid}".encode("utf-8")
    want = hmac.new(_secret(), payload, hashlib.sha256).digest()
    try:
        got = base64.urlsafe_b64decode(_b64url_fixpad(sig))
    except Exception:
        raise ValueError("bad_signature")

    if not hmac.compare_digest(want, got):
        raise ValueError("bad_signature")

    return gid, uid
