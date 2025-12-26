# bank.py
import json
from pathlib import Path
from typing import Dict

DATA_FILE = Path("balances.json")


def _load_data() -> Dict[str, int]:
    if not DATA_FILE.exists():
        return {}
    with DATA_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_data(data: Dict[str, int]) -> None:
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_balance(user_id: int) -> int:
    data = _load_data()
    return int(data.get(str(user_id), 0))


def set_balance(user_id: int, amount: int) -> None:
    data = _load_data()
    data[str(user_id)] = int(amount)
    _save_data(data)


def add_balance(user_id: int, amount: int) -> int:
    bal = get_balance(user_id)
    new_bal = bal + int(amount)
    set_balance(user_id, new_bal)
    return new_bal


def transfer(from_id: int, to_id: int, amount: int) -> bool:
    amount = int(amount)
    if amount <= 0:
        return False
    from_bal = get_balance(from_id)
    if from_bal < amount:
        return False
    # 差し引きと加算
    add_balance(from_id, -amount)
    add_balance(to_id, amount)
    return True