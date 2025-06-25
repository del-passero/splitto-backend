# src/utils/balance.py

from collections import defaultdict
from typing import Dict, List
from src.models.transaction import Transaction
from src.models.transaction_share import TransactionShare

def calculate_group_balances(transactions: List[Transaction], member_ids: List[int]) -> Dict[int, float]:
    """
    Считает итоговые нетто-балансы всех участников группы по всем транзакциям группы.
    Баланс > 0 — пользователю должны, < 0 — он должен другим.

    :param transactions: список транзакций группы
    :param member_ids: id всех участников группы
    :return: словарь {user_id: balance}
    """
    debts = defaultdict(lambda: defaultdict(float))  # debts[a][b]: сколько a должен b

    for tx in transactions:
        if tx.type == 'expense':
            payer = tx.paid_by
            for share in tx.shares:
                if share.user_id != payer:
                    # share.user_id должен payer'у
                    debts[share.user_id][payer] += share.amount
        elif tx.type == 'transfer':
            sender = tx.transfer_from
            for receiver_id in tx.transfer_to:
                if sender != receiver_id:
                    # sender перевёл receiver'у
                    debts[sender][receiver_id] += tx.amount

    # Считаем net balance для каждого участника (разница что должен/что должны ему)
    net_balance = {uid: 0 for uid in member_ids}
    for a in member_ids:
        for b in member_ids:
            net_balance[a] += debts[b][a] - debts[a][b]
    return net_balance

def calculate_global_balance(transactions: List[Transaction], user_id: int, friend_id: int) -> float:
    """
    Считает глобальный баланс между двумя пользователями по всем совместным транзакциям.
    Баланс > 0 — friend_id должен user_id, < 0 — наоборот.
    """
    balance = 0.0
    for tx in transactions:
        if tx.type == 'expense':
            payer = tx.paid_by
            for share in tx.shares:
                # только пары user_id/friend_id
                pair = {payer, share.user_id}
                if user_id in pair and friend_id in pair and payer != share.user_id:
                    if payer == user_id and share.user_id == friend_id:
                        balance += share.amount
                    elif payer == friend_id and share.user_id == user_id:
                        balance -= share.amount
        elif tx.type == 'transfer':
            if tx.transfer_from == user_id and friend_id in tx.transfer_to:
                balance += tx.amount
            elif tx.transfer_from == friend_id and user_id in tx.transfer_to:
                balance -= tx.amount
    return round(balance, 2)

def greedy_settle_up(net_balance: Dict[int, float]) -> List[Dict]:
    """
    Жадный алгоритм settle-up (минимизация переводов между участниками).

    :param net_balance: {user_id: balance}
    :return: список переводов [{"from_user_id": ..., "to_user_id": ..., "amount": ...}, ...]
    """
    settlements = []
    creditors = sorted([(uid, bal) for uid, bal in net_balance.items() if bal > 1e-2], key=lambda x: -x[1])
    debtors = sorted([(uid, bal) for uid, bal in net_balance.items() if bal < -1e-2], key=lambda x: x[1])

    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor_id, debt = debtors[i]
        creditor_id, credit = creditors[j]
        amount = min(-debt, credit)
        amount = round(amount, 2)
        if amount < 1e-2:
            if -debt < 1e-2: i += 1
            if credit < 1e-2: j += 1
            continue
        settlements.append({
            "from_user_id": debtor_id,
            "to_user_id": creditor_id,
            "amount": amount
        })
        debtors[i] = (debtor_id, debt + amount)
        creditors[j] = (creditor_id, credit - amount)
        if abs(debtors[i][1]) < 1e-2: i += 1
        if abs(creditors[j][1]) < 1e-2: j += 1
    return settlements
