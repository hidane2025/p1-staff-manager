"""P1 Staff Manager — 紙幣・硬貨内訳計算"""

from dataclasses import dataclass


DENOMINATIONS = [10000, 5000, 1000, 500, 100, 50, 10, 5, 1]

DENOM_LABELS = {
    10000: "1万円札",
    5000: "5千円札",
    1000: "千円札",
    500: "500円玉",
    100: "100円玉",
    50: "50円玉",
    10: "10円玉",
    5: "5円玉",
    1: "1円玉",
}


@dataclass(frozen=True)
class DenominationBreakdown:
    """1人分の紙幣・硬貨内訳"""
    amount: int
    bills: dict  # {10000: 2, 5000: 1, ...}


def calculate_denomination(amount: int) -> DenominationBreakdown:
    """金額を紙幣・硬貨に分解"""
    remaining = amount
    bills = {}
    for denom in DENOMINATIONS:
        count = remaining // denom
        if count > 0:
            bills[denom] = count
            remaining -= denom * count
    return DenominationBreakdown(amount=amount, bills=bills)


def calculate_total_denomination(amounts: list) -> dict:
    """複数人分の合計紙幣・硬貨内訳"""
    total = {d: 0 for d in DENOMINATIONS}
    for amount in amounts:
        breakdown = calculate_denomination(amount)
        for denom, count in breakdown.bills.items():
            total[denom] += count
    return {d: c for d, c in total.items() if c > 0}


def round_amount(amount: int, unit: int = 100) -> int:
    """端数切り上げ（小銭を減らす）

    例: round_amount(23450, 100) → 23500
        round_amount(23450, 500) → 23500
        round_amount(23450, 1000) → 24000
    """
    if amount % unit == 0:
        return amount
    return ((amount // unit) + 1) * unit


def format_denomination(bills: dict) -> str:
    """紙幣内訳を文字列に"""
    parts = []
    for denom in DENOMINATIONS:
        count = bills.get(denom, 0)
        if count > 0:
            parts.append(f"{DENOM_LABELS[denom]} × {count}")
    return "  /  ".join(parts)
