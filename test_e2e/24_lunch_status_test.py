"""弁当配布チェック（lunch_status）単体テスト（DB接続不要）

db.update_lunch_status / bulk_set_lunch_status / get_lunch_summary が共有する
バリデーションヘルパ `_validate_lunch_status` と定数 LUNCH_STATUSES の純関数を検証する。

実DBに依存する UPDATE/SELECT は別途E2Eで担保（このスイートは構文と状態空間の保証）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402


def test_lunch_statuses_constant_has_exactly_three() -> None:
    assert db.LUNCH_STATUSES == ("pending", "received", "cancelled"), db.LUNCH_STATUSES
    print("  ✅ LUNCH_STATUSES は3状態（pending/received/cancelled）")


def test_validate_accepts_received() -> None:
    assert db._validate_lunch_status("received") == "received"
    print("  ✅ 'received' を受け入れる")


def test_validate_accepts_pending() -> None:
    assert db._validate_lunch_status("pending") == "pending"
    print("  ✅ 'pending' を受け入れる")


def test_validate_accepts_cancelled() -> None:
    assert db._validate_lunch_status("cancelled") == "cancelled"
    print("  ✅ 'cancelled' を受け入れる")


def test_validate_normalizes_uppercase() -> None:
    # 大文字混在も小文字に正規化（タブレット入力時のブレ吸収）
    assert db._validate_lunch_status("RECEIVED") == "received"
    assert db._validate_lunch_status("Cancelled") == "cancelled"
    print("  ✅ 大文字混在を小文字に正規化")


def test_validate_strips_whitespace() -> None:
    assert db._validate_lunch_status(" received ") == "received"
    print("  ✅ 前後の空白を除去")


def test_validate_rejects_unknown() -> None:
    try:
        db._validate_lunch_status("absent")  # シフトの status と混同しないこと
    except ValueError as e:
        assert "lunch_status" in str(e)
        print("  ✅ 'absent' は弁当状態として拒否（シフト状態と混同しない）")
        return
    raise AssertionError("不正値で ValueError が出なかった")


def test_validate_rejects_none() -> None:
    try:
        db._validate_lunch_status(None)  # type: ignore[arg-type]
    except ValueError:
        print("  ✅ None は拒否（明示的に状態を渡す必要がある）")
        return
    raise AssertionError("None で ValueError が出なかった")


def _run(test: Callable[[], None]) -> bool:
    try:
        test()
        return True
    except AssertionError as exc:
        print(f"  ❌ {test.__name__}: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  💥 {test.__name__}: {type(exc).__name__}: {exc}")
        return False


if __name__ == "__main__":
    print("=== 弁当配布チェック（lunch_status）単体テスト ===")
    tests: list[Callable[[], None]] = [
        test_lunch_statuses_constant_has_exactly_three,
        test_validate_accepts_received,
        test_validate_accepts_pending,
        test_validate_accepts_cancelled,
        test_validate_normalizes_uppercase,
        test_validate_strips_whitespace,
        test_validate_rejects_unknown,
        test_validate_rejects_none,
    ]
    passed = 0
    failed = 0
    for t in tests:
        if _run(t):
            passed += 1
        else:
            failed += 1
    print(f"\n合計 {passed}/{passed + failed} PASS, {failed} FAIL")
    if failed:
        sys.exit(1)
    print("✅ 全テストPASS")
