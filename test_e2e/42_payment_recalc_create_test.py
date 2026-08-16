"""支払いレコードが未作成の人も再計算で作られることの回帰テスト（2026-08-16 追加）

再現した事故:
    NO.2020 上奨吾さん（受付・シフト5件・打刻3日）が支払い計算の一覧に
    まったく出てこなかった。一括計算を実行したあとに追加されたスタッフで、
    支払いレコードが1件も作られていなかった。
    打刻・CSV取込から呼ばれる再計算 (_recalc_one) が
    「prev is None ならスキップ」だったため、いくら打刻しても作られない。

固定する仕様:
  [A] 支払いレコードが無くても、シフトがある人は再計算で新規作成される。
  [B] シフトが1件も無い人には空の支払いを作らない（幽霊レコードを増やさない）。
  [C] 承認済み・支払済みは従来どおり触らない（中野さん指示の絶対条件）。
  [D] 既存レコードの臨時調整（adjustment）は再計算で消えない。

DB接続:
    本番DBには繋がない。_build_context と db.save_payment を差し替え、
    「保存が呼ばれたか」だけを見る純粋なロジックテスト。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/42_payment_recalc_create_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fake_db import install_fake_db  # noqa: E402

import db  # noqa: E402
from utils import payment_recalc  # noqa: E402

PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    print(f"  {PASS if cond else FAIL} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


STAFF = {"id": "st-2020", "no": 2020, "name_jp": "上奨吾", "role": "受付",
         "employment_type": "contractor", "custom_hourly_rate": 1350,
         "prefecture": None, "address": None, "region": None}
SHIFT = {"date": "2026-08-13", "start": "20:00", "end": "30:00", "is_mix": False}


def _ctx(payments: dict, with_shifts=True, punched=True):
    return {
        "ev": {"break_minutes_6h": 45, "break_minutes_8h": 60},
        "venue_key": "大阪",
        "rates": {"2026-08-13": {}},
        "rates_by_date": {"2026-08-13": {"hourly": 1350, "night": 1688,
                                         "transport": 0, "floor_bonus": 3000,
                                         "mix_bonus": 1500}},
        "rules": {}, "claims": {}, "allowances": {},
        "shifts_by_staff": {STAFF["id"]: [dict(SHIFT)]} if punched else {},
        "staff_with_shifts": {STAFF["id"]} if with_shifts else set(),
        "staff_by_id": {STAFF["id"]: dict(STAFF)},
        "payments": payments,
    }


def _run(ctx):
    """save_payment をスパイに差し替えて _recalc_one を実行する。"""
    install_fake_db({})
    saved: list = []
    original = db.save_payment
    db.save_payment = lambda **kw: saved.append(kw)  # type: ignore[assignment]
    try:
        ok = payment_recalc._recalc_one(11, STAFF["id"], ctx)
    finally:
        db.save_payment = original  # type: ignore[assignment]
    return ok, saved


print("\n[A] 支払いレコードが無い人も作られる")
ok, saved = _run(_ctx({}))
_check("新規スタッフでも再計算が成功する", ok is True, f"戻り値={ok}")
_check("支払いが1件保存される", len(saved) == 1, f"保存={len(saved)}件")
if saved:
    _check("金額が0ではない（打刻分が計上される）",
           int(saved[0].get("total_amount") or 0) > 0, str(saved[0].get("total_amount")))

print("\n[B] シフトが無い人には作らない（幽霊レコード防止）")
ok, saved = _run(_ctx({}, with_shifts=False, punched=False))
_check("シフト0件なら作らない", ok is False, f"戻り値={ok}")
_check("保存も呼ばれない", len(saved) == 0, f"保存={len(saved)}件")

print("\n[C] 承認済み・支払済みは触らない")
for _s in ("approved", "paid"):
    ok, saved = _run(_ctx({STAFF["id"]: {"status": _s, "adjustment": 0}}))
    _check(f"{_s} は再計算しない", ok is False and len(saved) == 0,
           f"戻り値={ok} 保存={len(saved)}件")

print("\n[D] 既存の臨時調整は消えない")
ok, saved = _run(_ctx({STAFF["id"]: {"status": "pending", "adjustment": -1000,
                                     "adjustment_note": "備品破損"}}))
_check("未承認なら再計算される", ok is True, f"戻り値={ok}")
if saved:
    _check("臨時調整が引き継がれる",
           int(saved[0].get("adjustment") or 0) == -1000, str(saved[0].get("adjustment")))
    _check("調整メモも引き継がれる",
           saved[0].get("adjustment_note") == "備品破損", str(saved[0].get("adjustment_note")))

print()
if failures:
    print(f"  {FAIL} {len(failures)}件 失敗")
    for f in failures:
        print(f"      {f}")
    sys.exit(1)
print(f"  {PASS} 全テスト PASS")
