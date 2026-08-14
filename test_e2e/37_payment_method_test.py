"""支払い方法マーカー（utils/payment_method.py）の単体テスト — DB非依存"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from utils import payment_method as pm  # noqa: E402

failures: list = []


def _check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + ("" if cond else f" — {detail}"))
    if not cond:
        failures.append(name)


_check("notesなし=現金", pm.method_of({"notes": None}) == "cash")
_check("空文字=現金", pm.method_of({"notes": ""}) == "cash")
_check("マーカーあり=振込", pm.method_of({"notes": "〔振込〕"}) == "transfer")
_check("マーカー+メモ=振込", pm.method_of({"notes": "〔振込〕口座は後日"}) == "transfer")
_check("メモ中間のマーカーは方法ではない",
       pm.method_of({"notes": "メモ〔振込〕"}) == "cash")
_check("free_note がマーカーを剥がす",
       pm.free_note({"notes": "〔振込〕 口座は後日"}) == "口座は後日")
_check("free_note 現金はそのまま",
       pm.free_note({"notes": "自由メモ"}) == "自由メモ")
_check("build_notes 振込", pm.build_notes("transfer", "メモ") == "〔振込〕メモ")
_check("build_notes 現金", pm.build_notes("cash", "メモ") == "メモ")
_check("build_notes 空メモ振込", pm.build_notes("transfer", "") == "〔振込〕")
_check("往復（set→parse）",
       pm.method_of({"notes": pm.build_notes("transfer", pm.free_note({"notes": "〔振込〕x"}))}) == "transfer")
for st_, m, want in [
    ("pending", "cash", "変動中"), ("approved", "transfer", "振込待ち"),
    ("paid", "cash", "現金支払い済み"), ("paid", "transfer", "振込済み"),
]:
    lab = pm.state_label({"status": st_, "notes": "〔振込〕" if m == "transfer" else ""})
    _check(f"状態表示 {st_}/{m}", want in lab, lab)

print("=" * 60)
if failures:
    print(f"❌ 失敗 {len(failures)}件")
    sys.exit(1)
print("✅ 全テスト成功")
