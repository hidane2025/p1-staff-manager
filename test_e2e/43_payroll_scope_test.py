"""精算対象外（社員）の除外 回帰テスト（2026-08-17 追加）

背景:
    社員（運営側スタッフ）は大会ごとの謝礼精算の対象ではないのに、
    シフトがある限り支払い一覧に出続けた。臨時調整で¥0にしても行は残り、
    一括計算を押せば計算し直される。NO.1 TAKA・NO.239 りんたろうで発生。

固定する仕様:
  [A] notes 先頭のマーカーで判定する（DDLを触れないため notes を使う）。
  [B] マーカーを付けても既存のメモは失わない。
  [C] 再計算は対象外スタッフの支払いを作らない・更新しない。
  [D] 対象外を解除すれば通常どおり計算される。

DB接続:
    本番DBには繋がない。純関数と、文脈を差し替えた _recalc_one だけを見る。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/43_payroll_scope_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fake_db import install_fake_db  # noqa: E402

import db  # noqa: E402
from utils import payroll_scope as ps  # noqa: E402
from utils import payment_recalc  # noqa: E402

PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    print(f"  {PASS if cond else FAIL} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


print("\n[A] マーカーで判定する")
_check("マーカー付きは対象外", ps.is_excluded({"notes": ps.MARKER + "社員"}))
_check("マーカーなしは対象", not ps.is_excluded({"notes": "遅刻多め"}))
_check("メモ空でも落ちない", not ps.is_excluded({"notes": None}))
_check("staffがNoneでも落ちない", not ps.is_excluded(None))
_check("マーカーが途中にあるだけなら対象",
       not ps.is_excluded({"notes": "備考 " + ps.MARKER}))

print("\n[B] 既存のメモを失わない")
_n = ps.build_notes(True, "社員（大会精算の対象外）")
_check("マーカー＋メモになる", _n == ps.MARKER + "社員（大会精算の対象外）", _n)
_check("メモだけ取り出せる",
       ps.free_note({"notes": _n}) == "社員（大会精算の対象外）",
       ps.free_note({"notes": _n}))
_check("解除するとメモだけ残る",
       ps.build_notes(False, "社員（大会精算の対象外）") == "社員（大会精算の対象外）")

print("\n[C] 再計算が対象外スタッフを作らない・更新しない")
STAFF = {"id": "st-1", "no": 1, "name_jp": "TAKA", "role": "TD",
         "employment_type": "contractor", "custom_hourly_rate": None,
         "prefecture": "大阪府", "address": "大阪府", "region": None}


def _ctx(notes, payments):
    s = dict(STAFF, notes=notes)
    return {
        "ev": {"break_minutes_6h": 45, "break_minutes_8h": 60},
        "venue_key": "大阪",
        "rates": {"2026-08-13": {}},
        "rates_by_date": {"2026-08-13": {"hourly": 1450, "night": 1812,
                                         "transport": 0, "floor_bonus": 3000,
                                         "mix_bonus": 1500}},
        "rules": {}, "claims": {}, "allowances": {},
        "shifts_by_staff": {"st-1": [{"date": "2026-08-13", "start": "10:00",
                                      "end": "20:00", "is_mix": False}]},
        "staff_with_shifts": {"st-1"},
        "staff_by_id": {"st-1": s},
        "payments": payments,
    }


def _run(ctx):
    install_fake_db({})
    saved: list = []
    original = db.save_payment
    db.save_payment = lambda **kw: saved.append(kw)  # type: ignore[assignment]
    try:
        ok = payment_recalc._recalc_one(11, "st-1", ctx)
    finally:
        db.save_payment = original  # type: ignore[assignment]
    return ok, saved


ok, saved = _run(_ctx(ps.MARKER + "社員", {}))
_check("対象外は新規作成されない", ok is False and not saved,
       f"戻り値={ok} 保存={len(saved)}件")

ok, saved = _run(_ctx(ps.MARKER + "社員", {"st-1": {"status": "pending", "adjustment": 0}}))
_check("既存レコードがあっても更新されない", ok is False and not saved,
       f"戻り値={ok} 保存={len(saved)}件")

print("\n[D] 解除すれば通常どおり計算される")
ok, saved = _run(_ctx("", {}))
_check("対象なら作成される", ok is True and len(saved) == 1,
       f"戻り値={ok} 保存={len(saved)}件")
if saved:
    _check("金額が計上される", int(saved[0].get("total_amount") or 0) > 0,
           str(saved[0].get("total_amount")))

print()
if failures:
    print(f"  {FAIL} {len(failures)}件 失敗")
    for f in failures:
        print(f"      {f}")
    sys.exit(1)
print(f"  {PASS} 全テスト PASS")
