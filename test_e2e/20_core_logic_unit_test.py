"""P1 Staff Manager — コアロジック ユニットテスト（v3.7 全機能チェック）

DB / Streamlit に依存せず、計算・パース・地域判定の純粋ロジックを検証する。
対象:
  - utils.calculator         — 支払い計算エンジン（時給×時間+深夜+手当+精勤+タイミー）
  - utils.denomination       — 紙幣・硬貨内訳
  - utils.region             — 都道府県→地域 マッピング
  - utils.shift_parser       — シフトCSV パース

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/20_core_logic_unit_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    mark = PASS if cond else FAIL
    print(f"  {mark} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


# ============================================================
# 1. calculator: parse_time_to_minutes / parse_shift_time
# ============================================================
print("\n[1] calculator: 時刻パース")
from utils.calculator import (
    parse_time_to_minutes, parse_shift_time, calculate_break_minutes,
    calculate_shift_hours, calculate_daily_pay, calculate_attendance_bonus,
    calculate_staff_payment,
)

_check("13:00 → 780分", parse_time_to_minutes("13:00") == 780)
_check("26:00 → 1560分（翌日扱い）", parse_time_to_minutes("26:00") == 1560)
_check("× は None", parse_time_to_minutes("×") is None)
_check("空文字は None", parse_time_to_minutes("") is None)
_check("13:00~23:00 → (780, 1380)",
       parse_shift_time("13:00~23:00") == (780, 1380))
_check("全角チルダ 13:00〜23:00 もパース",
       parse_shift_time("13:00〜23:00") == (780, 1380))
_check("ハイフン 13:00-23:00 もパース",
       parse_shift_time("13:00-23:00") == (780, 1380))


# ============================================================
# 2. calculator: 休憩時間
# ============================================================
print("\n[2] calculator: 休憩時間ロジック")
_check("4時間勤務は休憩0", calculate_break_minutes(4 * 60) == 0)
_check("7時間勤務は45分休憩", calculate_break_minutes(7 * 60) == 45)
_check("9時間勤務は60分休憩", calculate_break_minutes(9 * 60) == 60)
_check("ちょうど6時間は休憩0",
       calculate_break_minutes(6 * 60) == 0)
_check("カスタム値も反映",
       calculate_break_minutes(7 * 60, break_6h=30, break_8h=45) == 30)


# ============================================================
# 3. calculator: 1日分の計算（深夜手当）
# ============================================================
print("\n[3] calculator: シフト分解（通常+深夜+休憩）")
# 13:00~23:00 = 10時間勤務（うち22時以降は1時間）
# 休憩60分（8時間超）→ 通常 (9-1)時間 = 8時間, 深夜 1時間
sh = calculate_shift_hours(780, 1380, "2025-12-29")
_check("10時間勤務の通常時間 = 8h", sh.regular_minutes == 8 * 60,
       f"got {sh.regular_minutes}")
_check("10時間勤務の深夜時間 = 1h", sh.night_minutes == 60,
       f"got {sh.night_minutes}")
_check("10時間勤務の休憩 = 60分", sh.break_minutes == 60)


# ============================================================
# 4. calculator: 1日分の支払い
# ============================================================
print("\n[4] calculator: 1日分の支払い計算")
daily = calculate_daily_pay(
    sh, hourly_rate=1500, night_rate=1875,
    transport=1000, role="Dealer",
)
expected_base = 8 * 1500    # 12,000
expected_night = 1 * 1875   # 1,875
_check("基本給 = ¥12,000", daily.base_pay == expected_base,
       f"got ¥{daily.base_pay}")
_check("深夜手当 = ¥1,875", daily.night_pay == expected_night,
       f"got ¥{daily.night_pay}")
_check("交通費 = ¥1,000", daily.transport == 1000)
_check("Dealer はフロア手当なし", daily.floor_bonus == 0)
_check("Floor はフロア手当 ¥3,000",
       calculate_daily_pay(sh, 1500, 1875, 1000, "Floor").floor_bonus == 3000)
_check("MIX フラグONなら MIX手当 ¥1,500",
       calculate_daily_pay(sh, 1500, 1875, 1000, "Dealer", is_mix=True).mix_bonus == 1500)


# ============================================================
# 5. calculator: 精勤手当
# ============================================================
print("\n[5] calculator: 精勤手当")
_check("0日勤務 → ¥0", calculate_attendance_bonus(0, 6) == 0)
_check("4日勤務（6日中）→ ¥6,000", calculate_attendance_bonus(4, 6) == 6000)
_check("6日全勤（6日中）→ ¥10,000", calculate_attendance_bonus(6, 6) == 10000)
_check("3日大会・2日勤務 → ¥6,000", calculate_attendance_bonus(2, 3) == 6000)
# 2日大会の場合は閾値=2*2//3=1。1日勤務でも条件達成扱い（現行仕様）
_check("2日大会・1日勤務 → ¥6,000（閾値=2*2//3=1）",
       calculate_attendance_bonus(1, 2) == 6000)
_check("2日大会・0日勤務 → ¥0", calculate_attendance_bonus(0, 2) == 0)


# ============================================================
# 6. calculator: スタッフ1人通し計算（タイミー特殊扱い）
# ============================================================
print("\n[6] calculator: タイミー個別時給ルール")
shifts = [
    {"date": "2025-12-29", "start": "13:00", "end": "23:00", "is_mix": False},
    {"date": "2025-12-30", "start": "13:00", "end": "23:00", "is_mix": False},
]
rates = {
    "2025-12-29": {"hourly": 1500, "night": 1875, "transport": 1000,
                    "floor_bonus": 3000, "mix_bonus": 1500},
    "2025-12-30": {"hourly": 1500, "night": 1875, "transport": 1000,
                    "floor_bonus": 3000, "mix_bonus": 1500},
}
# 業務委託（通常）: base+night+交通費+Floor手当(なし=Dealer)+精勤(2/6=0)
contractor = calculate_staff_payment(
    1, "業務委託さん", "Dealer", shifts, rates, 6,
    employment_type="contractor",
)
# タイミー: 個別時給1200で通し計算、深夜割増なし、Floor/MIX/精勤なし
timee = calculate_staff_payment(
    2, "タイミーさん", "Dealer", shifts, rates, 6,
    employment_type="timee", custom_hourly_rate=1200,
)

_check("業務委託の精勤は対象（>=4日条件未達なので0）",
       contractor.attendance_bonus == 0)
_check("タイミーの精勤は除外", timee.attendance_bonus == 0)
_check("タイミーのフロア手当は0", timee.floor_bonus_total == 0)
_check("タイミーのMIX手当は0", timee.mix_bonus_total == 0)
_check("タイミーの深夜手当も通常時給で計算（割増なし）",
       # 1日10h勤務 - 1h休憩 = 9h（うち深夜1h）。通し時給1200で9h=10800円/日
       timee.base_pay + timee.night_pay == 9 * 1200 * 2,
       f"got ¥{timee.base_pay + timee.night_pay}")
_check("業務委託の交通費 ¥2,000",
       contractor.transport_total == 2000)
_check("タイミーも交通費は支給",
       timee.transport_total == 2000)


# ============================================================
# 7. denomination: 紙幣分解
# ============================================================
print("\n[7] denomination: 紙幣・硬貨内訳")
from utils.denomination import (
    calculate_denomination, calculate_total_denomination,
    round_amount, format_denomination,
)

b = calculate_denomination(23450)
_check("23,450円 = 1万×2 + 1千×3 + 500×0 + ...",
       b.bills == {10000: 2, 1000: 3, 100: 4, 50: 1},
       f"got {b.bills}")
_check("0円は空dict", calculate_denomination(0).bills == {})
_check("100円は100×1", calculate_denomination(100).bills == {100: 1})

total = calculate_total_denomination([10000, 5000, 1500])
_check("合計 [10000,5000,1500]: 1万×1+5千×1+千×1+500×1",
       total == {10000: 1, 5000: 1, 1000: 1, 500: 1},
       f"got {total}")

_check("23,450 → 100単位切り上げ → 23,500",
       round_amount(23450, 100) == 23500)
_check("23,450 → 500単位切り上げ → 23,500",
       round_amount(23450, 500) == 23500)
_check("23,450 → 1000単位切り上げ → 24,000",
       round_amount(23450, 1000) == 24000)
_check("ちょうど割り切れる場合は変えない",
       round_amount(23000, 1000) == 23000)

s = format_denomination({10000: 2, 1000: 3, 100: 4, 50: 1})
_check("format: '1万円札 × 2  /  千円札 × 3  /  100円玉 × 4  /  50円玉 × 1'",
       "1万円札 × 2" in s and "千円札 × 3" in s and "50円玉 × 1" in s,
       f"got '{s}'")


# ============================================================
# 8. region: 都道府県→地域
# ============================================================
print("\n[8] region: 都道府県・地域マッピング")
from utils.region import (
    extract_prefecture, prefecture_to_region, address_to_region,
    default_regions_for_event,
)

_check("住所から東京都抽出",
       extract_prefecture("東京都千代田区丸の内1-1-1") == "東京都")
_check("住所から愛知県抽出",
       extract_prefecture("愛知県名古屋市中区栄") == "愛知県")
_check("郵便番号付きでも抽出",
       extract_prefecture("〒100-0001 東京都千代田区") == "東京都")
_check("空文字はNone", extract_prefecture("") is None)
_check("Noneも安全", extract_prefecture(None) is None)

_check("東京都 → 関東", prefecture_to_region("東京都") == "関東")
_check("愛知県 → 東海", prefecture_to_region("愛知県") == "東海")
_check("北海道 → 北海道", prefecture_to_region("北海道") == "北海道")
_check("沖縄県 → 沖縄", prefecture_to_region("沖縄県") == "沖縄")
_check("不正値はNone",
       prefecture_to_region("架空県") is None)

pref, region = address_to_region("京都府京都市下京区")
_check("京都府住所 → 京都府/近畿",
       pref == "京都府" and region == "近畿")

# default_regions_for_event
rules = default_regions_for_event("愛知県")
_check("11地域分のルール生成", len(rules) == 11)
tokai = next(r for r in rules if r["region"] == "東海")
_check("愛知開催時、東海ルールはvenue扱い",
       tokai["is_venue_region"] == 1 and tokai["receipt_required"] == 0)
kanto = next(r for r in rules if r["region"] == "関東")
_check("愛知開催時、関東はvenueでない",
       kanto["is_venue_region"] == 0 and kanto["receipt_required"] == 1)


# ============================================================
# 9. shift_parser: 役職検出・日付パース
# ============================================================
print("\n[9] shift_parser: 役職検出・CSV パース")
from utils.shift_parser import (
    detect_role, normalize_digits, safe_int, parse_time_cell,
    detect_date_columns, normalize_date, parse_shift_csv,
)

_check("'TD' → 'TD'", detect_role("TD") == "TD")
_check("'フロア' → 'Floor'", detect_role("フロア") == "Floor")
_check("'ディーラー' → 'Dealer'", detect_role("ディーラー") == "Dealer")
_check("空文字は Dealer デフォルト", detect_role("") == "Dealer")

_check("全角数字 '１２３' → '123'",
       normalize_digits("１２３") == "123")
_check("safe_int('12') → 12", safe_int("12") == 12)
_check("safe_int(None) → 0", safe_int(None) == 0)
_check("safe_int('abc') → 0", safe_int("abc") == 0)

_check("× は None (parse_time_cell)", parse_time_cell("×") is None)
_check("13:00 はそのまま",
       parse_time_cell("13:00") == "13:00")

cols = ["役職", "NO.", "名前", "名前(英)", "12/29(月)", "12/30(火)", "1/2(金)"]
date_cols = detect_date_columns(cols)
_check("日付列を3列検出", len(date_cols) == 3,
       f"got {date_cols}")
_check("年跨ぎ判定: 12/29 → 2025、1/2 → 2026",
       normalize_date("12/29(月)", year=2025, ref_month=12) == "2025-12-29"
       and normalize_date("1/2(金)", year=2025, ref_month=12) == "2026-01-02")

# parse_shift_csv の最低限テスト
csv_text = (
    "役職,NO.,名前,名前(英),12/29(月),12/30(火)\n"
    "Dealer,1,EveKat,EVEKAT,13:00~23:00,×\n"
    "Floor,2,Yu,YU,12:00~22:00,8:00~18:00\n"
)
parsed = parse_shift_csv(csv_text.encode("utf-8"), year=2025)
_check("staffを2名検出", len(parsed["staff"]) == 2)
_check("dates 2日分", len(parsed["dates"]) == 2)
# Dealer 1日（×は除外）+ Floor 2日 = 3シフト
_check("shifts 3件", len(parsed["shifts"]) == 3,
       f"got {len(parsed['shifts'])}")


# ============================================================
# 結果集計
# ============================================================
print()
print("=" * 60)
if failures:
    print(f"{FAIL} 失敗 {len(failures)}件:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"{PASS} 全テスト成功")
    sys.exit(0)
