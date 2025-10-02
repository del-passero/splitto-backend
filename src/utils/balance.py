# src/utils/balance.py
# -----------------------------------------------------------------------------
# УТИЛИТЫ РАСЧЁТА БАЛАНСОВ / SETTLE-UP
# -----------------------------------------------------------------------------
# Политика:
#   • Мультивалютность без конверсии: считаем по каждой валюте отдельно.
#   • Нет межвалютного неттинга.
#   • Внутренние расчёты — Decimal, округление на уровне алгоритмов (по decimals).
#   • Семантика net:
#       net > 0 — пользователю ДОЛЖНЫ; net < 0 — он ДОЛЖЕН.
#   • Перевод (transfer) — ПОГАШЕНИЕ долга:
#       sender -> receiver на X уменьшает долг sender перед receiver на X,
#       что эквивалентно добавлению «анти-долга» receiver -> sender на X.
#   • Алгоритмы settle-up:
#       1) "greedy" — минимум переводов (сведение должников и кредиторов по net).
#       2) "pairs"  — парные долги «как в транзакциях» (без неттинга через третьих лиц).
# -----------------------------------------------------------------------------

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Iterable, Tuple
from collections import defaultdict

from src.models.transaction import Transaction
from src.models.transaction_share import TransactionShare


# =========================
# ВСПОМОГАТЕЛЬНОЕ
# =========================

def _D(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))

def _q(decimals: int) -> Decimal:
    return Decimal("1") if decimals <= 0 else Decimal("1").scaleb(-decimals)

def _round(d: Decimal, decimals: int) -> Decimal:
    return d.quantize(_q(decimals), rounding=ROUND_HALF_UP)

def _eps(decimals: int) -> Decimal:
    # малый порог; не менее 1e-2 и зависит от decimals
    return Decimal("1").scaleb(-max(decimals, 2))


# =========================
# МАТРИЦА ПАРНЫХ ДОЛГОВ
# =========================
# debts[ccy][a][b] = сколько a ДОЛЖЕН b в валюте ccy

def build_debts_matrix_by_currency(
    transactions: List[Transaction],
    member_ids: Iterable[int],
) -> Dict[str, Dict[int, Dict[int, Decimal]]]:
    member_ids = set(member_ids)
    debts: Dict[str, Dict[int, Dict[int, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(Decimal))
    )

    for tx in transactions:
        code = (getattr(tx, "currency_code", None) or "").upper()
        if not code:
            code = "XXX"  # безопасный fallback для «грязных» данных

        ttype = getattr(tx, "type", None)

        # --------------------
        # Расход
        # --------------------
        if ttype == "expense":
            payer = getattr(tx, "paid_by", None)
            if payer is None or payer not in member_ids:
                continue
            for share in getattr(tx, "shares", []) or []:
                uid = getattr(share, "user_id", None)
                if uid is None or uid == payer or uid not in member_ids:
                    continue
                amount = _D(getattr(share, "amount", 0))
                if amount:
                    # участник uid должен плательщику payer
                    debts[code][uid][payer] += amount

        # --------------------
        # Перевод (погашение)
        # --------------------
        elif ttype == "transfer":
            sender = getattr(tx, "transfer_from", None)
            if sender is None or sender not in member_ids:
                continue

            # 1) Если есть shares — используем их (адресные суммы), amount игнорируем
            shares_list = list(getattr(tx, "shares", []) or [])
            if shares_list:
                for share in shares_list:
                    rid = getattr(share, "user_id", None)
                    if rid is None or rid == sender or rid not in member_ids:
                        continue
                    sh = _D(getattr(share, "amount", 0))
                    if sh:
                        # анти-долг: rid -> sender на sh
                        debts[code][rid][sender] += sh
                continue

            # 2) Иначе fallback: amount на transfer_to (возможно несколько получателей)
            receivers = [r for r in (getattr(tx, "transfer_to", []) or []) if r in member_ids and r != sender]
            amount = _D(getattr(tx, "amount", 0))
            if not receivers or amount == 0:
                continue

            if len(receivers) == 1:
                rid = receivers[0]
                debts[code][rid][sender] += amount
            else:
                # равное деление суммы между валидными получателями (фикс критичного бага)
                per = amount / _D(len(receivers))
                for rid in receivers:
                    debts[code][rid][sender] += per

        # Прочие типы — игнорируем

    return debts


# =========================
# NET-БАЛАНСЫ ПО ВАЛЮТАМ
# =========================

def calculate_group_balances_by_currency(
    transactions: List[Transaction],
    member_ids: Iterable[int],
) -> Dict[str, Dict[int, Decimal]]:
    """
    Возвращает словарь по валютам:
      { "USD": {user_id: net, ...}, "EUR": {...}, ... }
    net > 0 — пользователю должны; net < 0 — он должен.

    Используется матрица debts[ccy][a][b] = сколько a ДОЛЖЕН b в валюте ccy.
    Нетто считается как входящие минус исходящие:
        net[a] += debts[b][a] - debts[a][b]
    """
    member_ids = list(member_ids)
    debts = build_debts_matrix_by_currency(transactions, member_ids)

    out: Dict[str, Dict[int, Decimal]] = {}
    for code, matrix in debts.items():
        net = {uid: Decimal("0") for uid in member_ids}
        for a in member_ids:
            for b in member_ids:
                if a == b:
                    continue
                net[a] += matrix[b][a] - matrix[a][b]
        out[code] = net
    return out


# =========================
# АЛГОРИТМЫ ВЫДАЧИ ПЛАНА
# =========================

def greedy_settle_up_single_currency(
    net_balance: Dict[int, Decimal],
    decimals: int,
    currency_code: str | None = None,
) -> List[Dict]:
    """
    Жадный settle-up для ОДНОЙ валюты.
    Возвращает список переводов: [{"from_user_id","to_user_id","amount","currency_code?"}, ...]
    """
    eps = _eps(decimals)

    creditors = sorted(
        [(uid, bal) for uid, bal in net_balance.items() if bal > eps],
        key=lambda x: (-x[1], x[0]),
    )
    debtors = sorted(
        [(uid, -bal) for uid, bal in net_balance.items() if bal < -eps],
        key=lambda x: (-x[1], x[0]),
    )

    settlements: List[Dict] = []
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor_id, debt_abs = debtors[i]
        creditor_id, credit_abs = creditors[j]

        amount = min(debt_abs, credit_abs)
        amount = _round(amount, decimals)

        if amount <= Decimal("0"):
            if debt_abs <= eps:
                i += 1
            if credit_abs <= eps:
                j += 1
            continue

        item = {"from_user_id": debtor_id, "to_user_id": creditor_id, "amount": float(amount)}
        if currency_code:
            item["currency_code"] = currency_code
        settlements.append(item)

        debtors[i] = (debtor_id, debt_abs - amount)
        creditors[j] = (creditor_id, credit_abs - amount)

        if debtors[i][1] <= eps:
            i += 1
        if creditors[j][1] <= eps:
            j += 1

    return settlements


def pairwise_settle_up_single_currency(
    debts_matrix: Dict[int, Dict[int, Decimal]],
    decimals: int,
    currency_code: str | None = None,
) -> List[Dict]:
    """
    Парные долги «как в транзакциях»:
      • агрегируем все долги a->b в матрице debts[a][b];
      • сводим ТОЛЬКО взаимные долги внутри пары A↔B;
      • без неттинга через третьих лиц.
    """
    eps = _eps(decimals)

    users: set[int] = set()
    for a, row in debts_matrix.items():
        users.add(a)
        users.update(row.keys())
    sorted_users = sorted(u for u in users if u is not None)

    settlements: List[Dict] = []
    for i, a in enumerate(sorted_users):
        for b in sorted_users[i + 1 :]:
            ab = debts_matrix.get(a, {}).get(b, Decimal("0"))
            ba = debts_matrix.get(b, {}).get(a, Decimal("0"))
            diff = ab - ba
            amt = _round(diff.copy_abs(), decimals)
            if amt <= eps:
                continue

            if diff > 0:
                item = {"from_user_id": a, "to_user_id": b, "amount": float(amt)}
            else:
                item = {"from_user_id": b, "to_user_id": a, "amount": float(amt)}
            if currency_code:
                item["currency_code"] = currency_code
            settlements.append(item)

    settlements.sort(key=lambda it: (it["from_user_id"], it["to_user_id"]))
    return settlements


def build_settle_plan_by_algorithm(
    *,
    transactions: List[Transaction],
    member_ids: Iterable[int],
    decimals_by_ccy: Dict[str, int],
    algorithm: str = "greedy",  # "greedy" | "pairs"
) -> List[Dict]:
    """
    Считает план по всем валютам согласно выбранному алгоритму.
    """
    algorithm = (algorithm or "greedy").lower().strip()

    if algorithm == "pairs":
        debts_by_ccy = build_debts_matrix_by_currency(transactions, member_ids)
        result: List[Dict] = []
        for ccy, matrix in debts_by_ccy.items():
            decs = int(decimals_by_ccy.get(ccy, 2))
            result.extend(pairwise_settle_up_single_currency(matrix, decs, currency_code=ccy))
        return result

    # default: greedy
    nets_by_ccy = calculate_group_balances_by_currency(transactions, member_ids)
    result: List[Dict] = []
    for ccy, per_user in nets_by_ccy.items():
        decs = int(decimals_by_ccy.get(ccy, 2))
        result.extend(greedy_settle_up_single_currency(per_user, decs, currency_code=ccy))
    return result
