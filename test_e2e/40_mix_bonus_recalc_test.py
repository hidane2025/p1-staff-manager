"""MIX手当が支払いに反映されることの回帰テスト（2026-08-16 追加）

再現した事故:
    出退勤画面でMIXにチェックを入れても MIX手当 ¥0 のままだった（NO.70 miwa）。
    原因は dbx/shifts.set_shift_mix がフラグだけ UPDATE し、
    支払いの差し戻し＋再計算（_revert_payment_if_amount_affected）を
    呼んでいなかったこと。打刻・欠勤・シフト再取込には同じフックが
    入っていたのに、MIXだけ漏れていた（QA第4巡で直した
    「全員退勤／全員リセットが再計算されない」と同じ型の欠陥）。

固定する仕様:
  [A] set_shift_mix は必ず差し戻し＋再計算を通す（ON/OFF どちらでも）。
  [B] 差し戻しには対象シフトの event_id / staff_id が渡る（人違い再計算の防止）。
  [C] 計算側: is_mix=True の日だけ mix_bonus が加算される。
  [D] 承認済み(approved)・支払済み(paid)は自動経路から絶対に触られない
      （2026-08-16 中野さん指示「承認済みは絶対に編集してはいけません」）。
      承認を外せるのは人が明示的に押す「↩️ 承認の取り消し」だけ
      （allow_approved=True）。支払済みはそこからも外せない。

DB接続:
    本番DBには繋がない。_fake_db.install_fake_db() で get_client を差し替え、
    再計算フックはスパイに置き換えて「呼ばれたか」だけを見る。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/40_mix_bonus_recalc_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fake_db import install_fake_db  # noqa: E402

from dbx import shifts as dbx_shifts  # noqa: E402
from utils.calculator import ShiftHours, calculate_daily_pay  # noqa: E402

PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    print(f"  {PASS if cond else FAIL} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


SHIFT = {"id": "sh-1", "event_id": 11, "staff_id": "st-70",
         "date": "2026-08-12", "is_mix": 0}


def _run_set_mix(value: int) -> list:
    """set_shift_mix を実行し、差し戻しフックに渡った引数を返す。"""
    install_fake_db({"p1_shifts": [dict(SHIFT)]})
    calls: list = []
    original = dbx_shifts._revert_payment_if_amount_affected
    dbx_shifts._revert_payment_if_amount_affected = (  # type: ignore[assignment]
        lambda row, reason: calls.append((row, reason)))
    try:
        dbx_shifts.set_shift_mix("sh-1", value)
    finally:
        dbx_shifts._revert_payment_if_amount_affected = original  # type: ignore[assignment]
    return calls


print("\n[A] MIXフラグの変更が再計算を通す")
on_calls = _run_set_mix(1)
_check("MIXをONにすると差し戻し＋再計算が走る", len(on_calls) == 1,
       f"呼び出し回数={len(on_calls)}（0なら手当が¥0のまま残る）")

off_calls = _run_set_mix(0)
_check("MIXをOFFにしても再計算が走る", len(off_calls) == 1,
       f"呼び出し回数={len(off_calls)}（外した手当が残り過払いになる）")

print("\n[B] 再計算の対象が正しい人・イベント")
if on_calls:
    row, reason = on_calls[0]
    _check("event_id が渡る", row.get("event_id") == 11, str(row))
    _check("staff_id が渡る", row.get("staff_id") == "st-70", str(row))
    _check("理由に日付が入る", "2026-08-12" in str(reason), str(reason))
else:
    _check("event_id が渡る", False, "フック未呼び出し")
    _check("staff_id が渡る", False, "フック未呼び出し")
    _check("理由に日付が入る", False, "フック未呼び出し")

print("\n[C] 計算側: is_mix の日だけ手当が乗る")
hours = ShiftHours(total_minutes=480, regular_minutes=480, night_minutes=0,
                   break_minutes=0, date="2026-08-12",
                   start_time="10:00", end_time="18:00")
without = calculate_daily_pay(hours, hourly_rate=1500, night_rate=1875,
                              transport=0, role="Dealer", is_mix=False)
with_mix = calculate_daily_pay(hours, hourly_rate=1500, night_rate=1875,
                               transport=0, role="Dealer", is_mix=True)
_check("is_mix=False は MIX手当 ¥0", without.mix_bonus == 0, str(without.mix_bonus))
_check("is_mix=True は MIX手当 ¥1,500", with_mix.mix_bonus == 1500, str(with_mix.mix_bonus))
_check("差額は MIX手当ちょうど",
       with_mix.daily_total - without.daily_total == 1500,
       f"{with_mix.daily_total} - {without.daily_total}")

print("\n[D] 承認済み・支払済みは自動経路から絶対に触られない（2026-08-16 中野さん指示）")
import dbx.payments as dbx_payments  # noqa: E402

for _status in ("approved", "paid"):
    install_fake_db({"p1_payments": [
        {"id": "pay-1", "event_id": 11, "staff_id": "st-70", "status": _status}]})
    ok = dbx_payments.reset_payment_to_pending(11, "st-70", reason="打刻修正")
    _check(f"{_status} は自動経路で差し戻されない", ok is False, f"戻り値={ok}")

install_fake_db({"p1_payments": [
    {"id": "pay-1", "event_id": 11, "staff_id": "st-70", "status": "approved"}]})
ok = dbx_payments.reset_payment_to_pending(
    11, "st-70", reason="承認取り消し（人が操作）", allow_approved=True)
_check("承認の取り消しUIからは戻せる", ok is True, f"戻り値={ok}")

install_fake_db({"p1_payments": [
    {"id": "pay-1", "event_id": 11, "staff_id": "st-70", "status": "paid"}]})
ok = dbx_payments.reset_payment_to_pending(
    11, "st-70", reason="承認取り消し（人が操作）", allow_approved=True)
_check("支払済みは人が操作しても戻せない", ok is False, f"戻り値={ok}")

install_fake_db({"p1_payments": [
    {"id": "pay-1", "event_id": 11, "staff_id": "st-70", "status": "pending"}]})
ok = dbx_payments.reset_payment_to_pending(11, "st-70", reason="打刻修正")
_check("未承認は従来どおり差し戻せる", ok is True, f"戻り値={ok}")


print()
if failures:
    print(f"  {FAIL} {len(failures)}件 失敗")
    for f in failures:
        print(f"      {f}")
    sys.exit(1)
print(f"  {PASS} 全テスト PASS")
