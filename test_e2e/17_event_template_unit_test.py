"""P1 Staff Manager — event_template モジュール ユニットテスト

DB に依存せずロジックだけ検証する pure unit test。
streamlitやsupabaseは import すらしないため、venv なし／オフライン実行可能。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/17_event_template_unit_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# event_template を import するために streamlit と supabase をスタブ化（DB側を遅延化）
# event_template 自体は streamlit を使わないが、念のため
import importlib

from utils import event_template as etpl


PASS = "✅"
FAIL = "❌"

failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    mark = PASS if cond else FAIL
    print(f"  {mark} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


# ============================================================
# 1. daterange
# ============================================================
print("\n[1] daterange")
_check("3日間", etpl.daterange("2026-08-13", "2026-08-15") ==
       ["2026-08-13", "2026-08-14", "2026-08-15"])
_check("単日", etpl.daterange("2026-08-13", "2026-08-13") == ["2026-08-13"])
_check("年跨ぎ", etpl.daterange("2025-12-30", "2026-01-02") ==
       ["2025-12-30", "2025-12-31", "2026-01-01", "2026-01-02"])
try:
    etpl.daterange("2026-08-15", "2026-08-13")
    _check("逆順は例外", False, "no exception")
except ValueError:
    _check("逆順は例外", True)


# ============================================================
# 2. RATE_PRESETS
# ============================================================
print("\n[2] RATE_PRESETS")
_check("p1_standard 存在", "p1_standard" in etpl.RATE_PRESETS)
_check("p1_standard regular 1500", etpl.RATE_PRESETS["p1_standard"]["regular"]["hourly"] == 1500)
_check("p1_standard premium 1600", etpl.RATE_PRESETS["p1_standard"]["premium"]["hourly"] == 1600)
_check("usop_standard 1400", etpl.RATE_PRESETS["usop_standard"]["regular"]["hourly"] == 1400)


# ============================================================
# 3. build_rates_from_preset
# ============================================================
print("\n[3] build_rates_from_preset")
dates = ["2026-08-13", "2026-08-14", "2026-08-15"]
rates = etpl.build_rates_from_preset("p1_standard", dates, premium_dates=["2026-08-15"])
_check("3日分生成", len(rates) == 3)
_check("通常日 hourly=1500", rates["2026-08-13"]["hourly"] == 1500)
_check("通常日 label=regular", rates["2026-08-13"]["date_label"] == "regular")
_check("プレミアム日 hourly=1600", rates["2026-08-15"]["hourly"] == 1600)
_check("プレミアム日 label=premium", rates["2026-08-15"]["date_label"] == "premium")
_check("プレミアム日 floor=5000", rates["2026-08-15"]["floor_bonus"] == 5000)

try:
    etpl.build_rates_from_preset("nonexistent", dates)
    _check("不明プリセットは例外", False)
except ValueError:
    _check("不明プリセットは例外", True)


# ============================================================
# 4. validate_template
# ============================================================
print("\n[4] validate_template")
valid_tmpl = {
    "name": "Test",
    "venue": "Test Hall",
    "start_date": "2026-08-13",
    "end_date": "2026-08-15",
    "rates": {
        "2026-08-13": {"hourly": 1500, "date_label": "regular"},
        "2026-08-14": {"hourly": 1500, "date_label": "regular"},
        "2026-08-15": {"hourly": 1600, "date_label": "premium"},
    },
    "transport_rules": [
        {"region": "東海", "max_amount": 8000},
        {"region": "関東", "max_amount": 15000},
    ],
}
_check("正常テンプレ → エラーなし", etpl.validate_template(valid_tmpl) == [])

bad1 = {**valid_tmpl, "name": ""}
_check("name 空は検出", any("name" in e for e in etpl.validate_template(bad1)))

bad2 = {**valid_tmpl, "start_date": "2026/08/13"}
_check("日付フォーマット異常を検出", any("YYYY-MM-DD" in e for e in etpl.validate_template(bad2)))

bad3 = {**valid_tmpl, "end_date": "2026-08-10"}  # 期間逆順
_check("期間逆順を検出", len(etpl.validate_template(bad3)) > 0)

bad4 = {**valid_tmpl, "rates": {**valid_tmpl["rates"],
        "2026-09-01": {"hourly": 1500, "date_label": "regular"}}}
_check("期間外の rates を検出", any("期間外" in e for e in etpl.validate_template(bad4)))

bad5 = {**valid_tmpl, "rates": {"2026-08-13": {"hourly": 1500, "date_label": "weird"}}}
_check("不正な date_label を検出", any("date_label" in e for e in etpl.validate_template(bad5)))

bad6 = {**valid_tmpl, "transport_rules": [
    {"region": "東海", "max_amount": 8000},
    {"region": "東海", "max_amount": 9000},
]}
_check("region 重複を検出", any("重複" in e for e in etpl.validate_template(bad6)))


# ============================================================
# 5. load_template / dump_template
# ============================================================
print("\n[5] load_template / dump_template (round-trip)")
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
    json.dump(valid_tmpl, f, ensure_ascii=False)
    tmppath = f.name
try:
    loaded = etpl.load_template(tmppath)
    _check("load_template でファイル読み込み", loaded["name"] == "Test")
    dumped = etpl.dump_template(loaded)
    _check("dump_template で日本語を保持", "Test Hall" in dumped)
    redumped = json.loads(dumped)
    _check("ラウンドトリップ一致", redumped == loaded)
finally:
    os.unlink(tmppath)


# ============================================================
# 6. 内蔵テンプレ全部が validate を通る
# ============================================================
print("\n[6] 内蔵テンプレの検証")
templates_dir = ROOT / "docs" / "event_templates"
for fp in sorted(templates_dir.glob("*.json")):
    if fp.name.startswith("_TEMPLATE_BLANK"):
        continue  # blank はプレースホルダなのでスキップ
    tmpl = etpl.load_template(fp)
    errs = etpl.validate_template(tmpl)
    _check(f"{fp.name}", errs == [], f"errors: {errs}")


# ============================================================
# 結果集計
# ============================================================
print()
print("=" * 60)
if failures:
    print(f"{FAIL} 失敗: {len(failures)}件")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"{PASS} 全テスト成功")
    sys.exit(0)
