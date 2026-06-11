"""スタッフ名寄せ（同一人物判定）単体テスト（DB接続不要）

db.bulk_import_staff / find_or_create_staff が使う名寄せ純関数
（_norm_key / _build_staff_index / _match_staff）を検証する。

源泉徴収・法定調書を「人単位」で正確に集計するには、同一人物が表記揺れや
二重送信で別IDに分裂しないことが前提。ここがその防波堤。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402  (streamlit を import するが、純関数呼び出しのみで実行コンテキスト不要)


# ---------------------------------------------------------------------------
# _norm_key
# ---------------------------------------------------------------------------

def test_norm_key_handles_width_case_space() -> None:
    # 全角/半角・空白・大文字小文字の揺れをすべて吸収
    assert db._norm_key("Eve Kat") == db._norm_key("ＥＶＥ　ＫＡＴ")
    assert db._norm_key("EveKat") == db._norm_key("eve kat")
    assert db._norm_key(" 久遠 ") == db._norm_key("久遠")
    assert db._norm_key("") == ""
    assert db._norm_key(None) == ""
    print("  ✅ 正規化キー（全角/半角・空白・大小を吸収）")


# ---------------------------------------------------------------------------
# _match_staff（照合優先度: NO. > email > name_jp）
# ---------------------------------------------------------------------------

def test_match_by_no_is_top_priority() -> None:
    idx = db._build_staff_index([{"id": 1, "no": 18, "name_jp": "EveKat", "email": ""}])
    ex, by = db._match_staff(18, "全然違う名前", "", idx)
    assert ex and ex["id"] == 1 and by == "no", (ex, by)
    print("  ✅ NO.一致が最優先")


def test_match_by_email_case_insensitive() -> None:
    idx = db._build_staff_index([{"id": 2, "no": None, "name_jp": "久遠", "email": "a@b.com"}])
    ex, by = db._match_staff(None, "別の源氏名", "A@B.COM", idx)
    assert ex and ex["id"] == 2 and by == "email", (ex, by)
    print("  ✅ メール一致（大文字小文字無視）")


def test_match_by_normalized_name() -> None:
    idx = db._build_staff_index([{"id": 3, "no": None, "name_jp": "Eve Kat", "email": ""}])
    ex, by = db._match_staff(None, "ＥＶＥ　ＫＡＴ", "", idx)  # 全角＋スペース揺れ
    assert ex and ex["id"] == 3 and by == "name_jp", (ex, by)
    print("  ✅ 源氏名の表記揺れを吸収して同一人物と判定")


def test_match_name_multi_flagged() -> None:
    idx = db._build_staff_index([
        {"id": 4, "no": None, "name_jp": "Ace", "email": ""},
        {"id": 5, "no": None, "name_jp": "ace", "email": ""},
    ])
    ex, by = db._match_staff(None, "ACE", "", idx)
    assert by == "name_jp_multi", (ex, by)
    print("  ✅ 同名が複数 → 要確認フラグ(name_jp_multi)")


def test_no_match_returns_none() -> None:
    idx = db._build_staff_index([{"id": 6, "no": 18, "name_jp": "X", "email": ""}])
    ex, by = db._match_staff(99, "新人さん", "new@example.com", idx)
    assert ex is None and by == "", (ex, by)
    print("  ✅ どのキーも一致しなければ新規（None）")


def test_no_priority_over_email() -> None:
    # NO.一致とメール一致が別レコードを指す場合、NO.が勝つ
    idx = db._build_staff_index([
        {"id": 7, "no": 18, "name_jp": "A", "email": "a@x.com"},
        {"id": 8, "no": 20, "name_jp": "B", "email": "b@x.com"},
    ])
    ex, by = db._match_staff(18, "B", "b@x.com", idx)
    assert ex["id"] == 7 and by == "no", (ex, by)
    print("  ✅ NO. > メール の優先順位")


def test_index_add_absorbs_in_batch_duplicate() -> None:
    # 同一バッチ内で同じ人を2回入れても、2回目は既存として拾える
    idx = db._build_staff_index([])
    ex, by = db._match_staff(None, "久遠", "k@x.com", idx)
    assert ex is None  # 1回目は新規
    db._index_add(idx, {"id": 99, "no": None, "name_jp": "久遠", "email": "k@x.com"})
    ex2, by2 = db._match_staff(None, "久 遠", "", idx)  # 表記揺れでも拾う
    assert ex2 and ex2["id"] == 99 and by2 == "name_jp", (ex2, by2)
    print("  ✅ 同一バッチ内の二重取込を吸収")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

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
    print("=== スタッフ名寄せ（同一人物判定）単体テスト ===")
    tests: list[Callable[[], None]] = [
        test_norm_key_handles_width_case_space,
        test_match_by_no_is_top_priority,
        test_match_by_email_case_insensitive,
        test_match_by_normalized_name,
        test_match_name_multi_flagged,
        test_no_match_returns_none,
        test_no_priority_over_email,
        test_index_add_absorbs_in_batch_duplicate,
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
