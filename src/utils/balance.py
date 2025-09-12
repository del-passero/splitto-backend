# src/utils/balance.py
# -----------------------------------------------------------------------------
# УТИЛИТЫ РАСЧЁТА БАЛАНСОВ / SETTLE-UP
# -----------------------------------------------------------------------------
# Политика:
#   • Мультивалютность без конверсии: считаем по каждой валюте отдельно.
#   • Нет межвалютного неттинга.
#   • Внутренние расчёты — Decimal, округление отдаём на уровень роутера (по decimals).
# -----------------------------------------------------------------------------

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Iterable
from collections import defaultdict

from src.models.transaction import Transaction
from src.models.transaction_share import TransactionShare


def _ensure_decimal(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def calculate_group_balances_by_currency(
    transactions: List[Transaction],
    member_ids: Iterable[int],
) -> Dict[str, Dict[int, Decimal]]:
    """
    Возвращает словарь по валютам:
      { "USD": {user_id: net, ...}, "EUR": {...}, ... }
    net > 0 — пользователю должны; net < 0 — он должен.
    """
    member_ids = list(member_ids)
    # debts[ccy][a][b] = сколько a должен b в валюте ccy
    debts: Dict[str, Dict[int, Dict[int, Decimal]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))

    for tx in transactions:
        code = (tx.currency_code or "").upper()
        if not code:
            # безопасная защита от пустых значений
            code = "XXX"

        if tx.type == "expense":
            payer = tx.paid_by
            if payer is None:
                continue
            for share in tx.shares:
                if share.user_id != payer:
                    debts[code][share.user_id][payer] += _ensure_decimal(share.amount)
        elif tx.type == "transfer":
            sender = tx.transfer_from
            if sender is None:
                continue
            receivers = tx.transfer_to or []
            for receiver_id in receivers:
                if sender != receiver_id:
                    debts[code][sender][receiver_id] += _ensure_decimal(tx.amount)

    out: Dict[str, Dict[int, Decimal]] = {}
    for code, matrix in debts.items():
        net = {uid: Decimal("0") for uid in member_ids}
        for a in member_ids:
            for b in member_ids:
                net[a] += matrix[b][a] - matrix[a][b]
        out[code] = net
    return out


def greedy_settle_up_single_currency(
    net_balance: Dict[int, Decimal],
    decimals: int,
    currency_code: str | None = None,
) -> List[Dict]:
    """
    Жадный settle-up для ОДНОЙ валюты.
    Возвращает список переводов: [{"from_user_id", "to_user_id", "amount", "currency_code?"}, ...]
    """
    def _round_amount(d: Decimal) -> Decimal:
        if decimals <= 0:
            return d.quantize(Decimal("1"))
        return d.quantize(Decimal("1").scaleb(-decimals))

    eps = Decimal("1").scaleb(-max(decimals, 2))  # малый порог

    creditors = sorted([(uid, bal) for uid, bal in net_balance.items() if bal > eps], key=lambda x: -x[1])
    debtors = sorted([(uid, bal) for uid, bal in net_balance.items() if bal < -eps], key=lambda x: x[1])

    settlements: List[Dict] = []
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor_id, debt = debtors[i]
        creditor_id, credit = creditors[j]
        amount = min(-debt, credit)
        amount = _round_amount(amount)
        if amount <= Decimal("0"):
            if -debt <= eps: i += 1
            if credit <= eps: j += 1
            continue

        item = {
            "from_user_id": debtor_id,
            "to_user_id": creditor_id,
            "amount": float(amount),
        }
        if currency_code:
            item["currency_code"] = currency_code
        settlements.append(item)

        debtors[i] = (debtor_id, debt + amount)
        creditors[j] = (creditor_id, credit - amount)
        if abs(debtors[i][1]) <= eps: i += 1
        if abs(creditors[j][1]) <= eps: j += 1

    return settlements
