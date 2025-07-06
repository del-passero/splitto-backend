from fastapi import APIRouter, HTTPException, Request
import hmac, hashlib, os

router = APIRouter()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
print("TELEGRAM_BOT_TOKEN =", repr(TELEGRAM_BOT_TOKEN))

@router.post("/telegram")
async def telegram_auth(request: Request):
    data = await request.json()
    init_data = data.get("initData")
    print("init_data:", init_data)
    if not init_data:
        raise HTTPException(400, "initData is required")
    # Парсим руками, чтобы не декодировалось ничего
    params = []
    hash_from_telegram = None
    for pair in init_data.split('&'):
        k, v = pair.split('=', 1)
        if k == 'hash':
            hash_from_telegram = v
        elif k != 'signature':
            params.append((k, v))
    params.sort(key=lambda x: x[0])
    data_check_string = '\n'.join(f"{k}={v}" for k, v in params)
    print("data_check_string:\n", data_check_string)
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    print("calculated_hash:", calculated_hash)
    print("hash_from_telegram:", hash_from_telegram)
    if not hmac.compare_digest(calculated_hash, hash_from_telegram):
        print("❌ Подпись не совпадает!")
        raise HTTPException(401, "Неверная подпись Telegram WebApp (initData)")
    print("✅ Подпись совпала!")
    return {"ok": True}
