"""P1 Staff Manager — 勤務時間・深夜割増 回帰テスト（QA確定欠陥の再現）

QA で確定した utils/calculator.py の欠陥を再現・固定するためのテスト。
「今のコードで赤になる」ことが目的なので、修正が入るまで失敗し続ける。

対象欠陥:
  (A) 退勤 < 出勤 のとき全ゼロを黙って返す（calculator.py:110-113）
      13:00 出勤 / 01:00 退勤（打刻ミス）が ShiftHours(0,0,0,0) になり、
      基本給 ¥0 のまま封筒まで通る。呼び出し側が「不正入力」と判別できない。
  (B) 全角チルダ U+FF5E「～」がパースできない（calculator.py:83-84）
      置換対象が U+301C / U+FF0D / ASCII "-" のみで、日本語入力で最も出やすい
      U+FF5E と長音符 U+30FC が None になる → シフトが丸ごと無視される。
  (C) 深夜割増に「翌5:00」の上限が無い（calculator.py:7, 118-131）
      SPEC.md:242「night_rate を 22:00〜翌5:00 に適用」に反し、
      22:00 以降が無制限に深夜扱い / 0:00〜5:00 が通常扱いになる。
  (D) 境界値（現状は正しい）。修正時に壊さないための回帰ガード。

DB には一切接続しない（utils.calculator / utils.denomination は
dataclasses しか import しない純粋ロジック。_fake_db も不要）。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/30_worktime_regression_test.py
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


from utils.calculator import (  # noqa: E402
    parse_shift_time,
    calculate_break_minutes,
    calculate_shift_hours,
    calculate_daily_pay,
    calculate_staff_payment,
)
from utils.denomination import round_amount  # noqa: E402


# テスト全体で使う単価。SPEC の標準レート（通常1500 / 深夜1875 = 1.25倍）。
HOURLY = 1500
NIGHT = 1875


# ============================================================
# (A) 退勤 < 出勤 は「不正入力」として検知できなければならない
# ============================================================
print("\n[A] 退勤 < 出勤（打刻ミス）の扱い")

# 13:00 出勤・01:00 退勤。翌1:00 のつもりなら 25:00 と入力すべきで、
# 01:00 のままだと start=780分 > end=60分 になる。
# total = 60 - 780 = -720分。現状は total <= 0 で ShiftHours(0,0,0,0) を黙って返す。
_a_error = None
_a_result = None
try:
    _a_result = calculate_shift_hours(780, 60, "2025-12-29")
except (ValueError, ArithmeticError) as e:
    _a_error = e

# 呼び出し側が「不正」と判別できる形は、次のいずれかであれば良い（実装は問わない）:
#   (1) 例外を送出する
#   (2) None を返す
#   (3) ShiftHours に不正フラグ（is_invalid / error 等）を持たせる
_a_detected = (
    _a_error is not None
    or _a_result is None
    or bool(getattr(_a_result, "is_invalid", False))
    or getattr(_a_result, "error", None) is not None
)
# 【設計判断 2026-08-02】
# 当初この検査は「end<start は例外にすべき」としていたが、実装は
# 「翌日の時刻として解釈する（01:00 → 25:00）」を選んだ。理由:
#   ・13:00出勤で「01:00」と打刻する人が意図しているのは翌日の1時であり、
#     エラーで弾くとピット端末の行列が深夜に止まる
#   ・エラーにしても、その場で25:00に直せなければ結局0円のまま確定しうる
#   ・あり得ない長さ（20時間超）は InvalidShiftError で別途弾いている
# したがって本検査の要件は「黙って0円にしないこと」であり、
# それを満たす形として①正常な12時間勤務として解釈される ②または不正として検知される
# のいずれかを許容する。0分に化ける（＝賃金が消える）ことだけは許さない。
_a_normalized = (
    _a_result is not None
    and _a_result.total_minutes == 720          # 13:00〜翌1:00 = 12時間
    and _a_result.total_minutes > 0
)
_check(
    "A-1 退勤<出勤 が黙って0分にならない（翌日解釈 or 不正検知のいずれか）",
    _a_detected or _a_normalized,
    f"0分に化けた: {_a_result!r}（賃金が消える）",
)

# 現状の返り値そのものを固定しておく。修正後にここが変わること自体が「直った証拠」。
# 期待は「total_minutes が負の値のまま保持される」か「そもそも返さない」のどちらか。
# 少なくとも -720分の入力が total_minutes=0 に化けるのは情報の消失。
_check(
    "A-2 不正入力の total_minutes が 0 に化けない",
    _a_result is None or _a_result.total_minutes != 0,
    f"total_minutes={getattr(_a_result, 'total_minutes', None)} "
    "（実際は -720分の入力。0 に丸められ差分が消えている）",
)

# 下流への影響: そのまま calculate_staff_payment に流すと基本給 ¥0 で通る。
# 1日大会で1日勤務なので精勤手当 ¥10,000 は満額付き、交通費 ¥1,000 も出る。
#   base_pay = 0 / night_pay = 0 / transport = 1,000 / attendance = 10,000
#   total_amount = 11,000 → 「働いたのに時給分だけ ¥0」の封筒が出来上がる。
_a_payment = calculate_staff_payment(
    staff_id=1,
    name="打刻ミス太郎",
    role="Dealer",
    shifts=[{"date": "2025-12-29", "start": "13:00", "end": "01:00"}],
    rates_by_date={"2025-12-29": {"hourly": HOURLY, "night": NIGHT, "transport": 1000}},
    total_event_days=1,
)
# 正しい挙動は「例外」「そのシフトを days_worked に数えない」「基本給が発生する」の
# いずれか。days_worked=1 なのに base_pay=0 という組み合わせだけは許されない。
_check(
    "A-3 勤務1日として計上されたのに基本給 ¥0 にならない",
    not (_a_payment.days_worked == 1 and _a_payment.base_pay == 0),
    f"days_worked={_a_payment.days_worked} / base_pay=¥{_a_payment.base_pay} / "
    f"total_amount=¥{_a_payment.total_amount}"
    "（時給分が丸ごと欠落したまま精勤手当だけ満額）",
)


# ============================================================
# (B) 区切り文字のパース（全角チルダ・長音符）
# ============================================================
print("\n[B] シフト時刻の区切り文字パース")

# 期待値の根拠: 13:00 = 13*60 = 780分 / 23:00 = 23*60 = 1380分
EXPECTED_RANGE = (780, 1380)

# U+FF5E FULLWIDTH TILDE。Windows の日本語IMEで「から」を変換した時の既定字形。
# 実務のシフト表で最も出やすいのにこれ。calculator.py:83 の置換対象に無い。
_check(
    "B-1 全角チルダ U+FF5E『13:00～23:00』→ (780, 1380)",
    parse_shift_time("13:00～23:00") == EXPECTED_RANGE,
    f"got {parse_shift_time('13:00～23:00')!r}"
    "（None = シフトが丸ごと無視され、その日の給与が消える）",
)

# U+30FC KATAKANA-HIRAGANA PROLONGED SOUND MARK（長音符「ー」）。
# 全角ハイフンのつもりで打たれる代表的な誤入力。
_check(
    "B-2 長音符 U+30FC『13:00ー23:00』→ (780, 1380)",
    parse_shift_time("13:00ー23:00") == EXPECTED_RANGE,
    f"got {parse_shift_time('13:00ー23:00')!r}",
)

# 以下3つは現状も通る。修正時に潰さないための回帰ガード。
# U+301C WAVE DASH（macOS の日本語IMEの既定字形）
_check(
    "B-3 波ダッシュ U+301C『13:00〜23:00』→ (780, 1380)【現状OK】",
    parse_shift_time("13:00〜23:00") == EXPECTED_RANGE,
    f"got {parse_shift_time('13:00〜23:00')!r}",
)
# ASCII HYPHEN-MINUS
_check(
    "B-4 半角ハイフン『13:00-23:00』→ (780, 1380)【現状OK】",
    parse_shift_time("13:00-23:00") == EXPECTED_RANGE,
    f"got {parse_shift_time('13:00-23:00')!r}",
)
# U+FF0D FULLWIDTH HYPHEN-MINUS
_check(
    "B-5 全角ハイフン U+FF0D『13:00－23:00』→ (780, 1380)【現状OK】",
    parse_shift_time("13:00－23:00") == EXPECTED_RANGE,
    f"got {parse_shift_time('13:00－23:00')!r}",
)
# 区切りの前後に空白が入るケース（コピペで混入する）
_check(
    "B-6 空白混じり『13:00 ~ 23:00』→ (780, 1380)【現状OK】",
    parse_shift_time("13:00 ~ 23:00") == EXPECTED_RANGE,
    f"got {parse_shift_time('13:00 ~ 23:00')!r}",
)


# ============================================================
# (C) 深夜割増は 22:00〜翌5:00 の窓に収まらなければならない（SPEC.md:242）
# ============================================================
print("\n[C] 深夜割増の適用範囲（22:00〜翌5:00）")

NIGHT_WINDOW_START = 22 * 60   # 1320分
NIGHT_WINDOW_END = 29 * 60     # 翌5:00 = 24*60 + 5*60 = 1740分

# --- C-1: 0:00〜5:00 は全部が深夜窓の内側 ---
# total = 300 - 0 = 300分（5時間）。6時間以下なので休憩は0分。
# 22:00〜翌5:00 の窓に完全に含まれるので 深夜300分 / 通常0分 が正しい。
# 現状は end(300) <= 1320 の分岐に落ちて全部が通常時間になる。
sh_c1 = calculate_shift_hours(0, 300, "2025-12-30")
_check(
    "C-1a 0:00〜5:00 は深夜 300分（5h）",
    sh_c1.night_minutes == 300,
    f"got night={sh_c1.night_minutes}分 / regular={sh_c1.regular_minutes}分",
)
_check(
    "C-1b 0:00〜5:00 に通常時間は無い（0分）",
    sh_c1.regular_minutes == 0,
    f"got regular={sh_c1.regular_minutes}分",
)
# 金額根拠: 深夜 5h × ¥1,875 = ¥9,375 / 基本給 ¥0
# 現状は 5h × ¥1,500 = ¥7,500 が基本給に入り、深夜 ¥0 → ¥1,875 の過少支給。
pay_c1 = calculate_daily_pay(sh_c1, hourly_rate=HOURLY, night_rate=NIGHT,
                             transport=0, role="Dealer")
_check(
    "C-1c 0:00〜5:00 の深夜手当 = ¥9,375（5h × ¥1,875）",
    pay_c1.night_pay == 9375,
    f"got 深夜¥{pay_c1.night_pay} / 基本¥{pay_c1.base_pay}"
    f"（正しくは 深夜¥9,375・基本¥0。差額 ¥{9375 - pay_c1.night_pay - pay_c1.base_pay} の過少支給）",
)

# --- C-2: 22:00〜30:00（翌6:00）は 翌5:00 で切れる ---
# 休憩控除OFF（Pacific 運用 break_6h=0 / break_8h=0）で休憩の按分要素を排除して検証する。
# total = 1800 - 1320 = 480分（8時間）。休憩0分。
# 深夜 = 1740 - 1320 = 420分（7時間、22:00〜翌5:00）
# 通常 = 1800 - 1740 =  60分（1時間、翌5:00〜翌6:00）
sh_c2 = calculate_shift_hours(1320, 1800, "2025-12-30", break_6h=0, break_8h=0)
_check(
    "C-2a 22:00〜30:00 の深夜 = 420分（7h）",
    sh_c2.night_minutes == 420,
    f"got night={sh_c2.night_minutes}分（翌5:00 の上限が無く 480分すべてを深夜にしている）",
)
_check(
    "C-2b 22:00〜30:00 の通常 = 60分（翌5:00〜翌6:00）",
    sh_c2.regular_minutes == 60,
    f"got regular={sh_c2.regular_minutes}分",
)
# 金額根拠: 深夜 7h × ¥1,875 = ¥13,125 / 基本 1h × ¥1,500 = ¥1,500 → 合計 ¥14,625
# 現状は 深夜 8h × ¥1,875 = ¥15,000 / 基本 ¥0 → ¥15,000。¥375 の過払い。
pay_c2 = calculate_daily_pay(sh_c2, hourly_rate=HOURLY, night_rate=NIGHT,
                             transport=0, role="Dealer")
_check(
    "C-2c 22:00〜30:00 の賃金 = ¥14,625（深夜¥13,125 + 基本¥1,500）",
    pay_c2.night_pay == 13125 and pay_c2.base_pay == 1500,
    f"got 深夜¥{pay_c2.night_pay} + 基本¥{pay_c2.base_pay} = "
    f"¥{pay_c2.night_pay + pay_c2.base_pay}（正しくは ¥14,625）",
)

# --- C-3: 休憩をどう按分しても、深夜が420分を超えることはあり得ない ---
# 既定の休憩設定（6時間超=45分）でも、深夜窓の物理的な長さ 420分 が上限。
# total=480分 → 480 > 360 なので休憩45分。現状は 480-45=435分すべてを深夜にしている。
sh_c3 = calculate_shift_hours(1320, 1800, "2025-12-30")
_check(
    "C-3 休憩あり(45分)でも深夜は 420分（7h）を超えない",
    sh_c3.night_minutes <= 420,
    f"got night={sh_c3.night_minutes}分 > 420分"
    "（22:00〜翌5:00 の窓そのものが420分しかないので物理的に不可能）",
)

# --- C-4: 22:00 をまたいで 翌5:00 の手前で終わるケース（現状OK・回帰ガード） ---
# 20:00〜28:00（翌4:00）。休憩控除OFF。
# total = 1680 - 1200 = 480分。
# 通常 = 1320 - 1200 = 120分（20:00〜22:00）
# 深夜 = 1680 - 1320 = 360分（22:00〜翌4:00。翌5:00 の手前なので全部が深夜）
sh_c4 = calculate_shift_hours(1200, 1680, "2025-12-30", break_6h=0, break_8h=0)
_check(
    "C-4a 20:00〜28:00 の通常 = 120分（2h）【現状OK】",
    sh_c4.regular_minutes == 120,
    f"got regular={sh_c4.regular_minutes}分",
)
_check(
    "C-4b 20:00〜28:00 の深夜 = 360分（6h）【現状OK】",
    sh_c4.night_minutes == 360,
    f"got night={sh_c4.night_minutes}分",
)

# --- C-5: 22:00 前に始まり 翌5:00 を越えて終わる（通常時間が2箇所に割れる） ---
# 21:00〜30:00（翌6:00）。休憩控除OFF。
# total = 1800 - 1260 = 540分（9時間）。
# 通常 = (1320-1260)=60分【21:00〜22:00】 + (1800-1740)=60分【翌5:00〜翌6:00】= 120分
# 深夜 = 1740 - 1320 = 420分（7時間）
# 現状は 深夜が 1800-1320=480分 になり、翌5:00 以降の通常1時間が消える。
sh_c5 = calculate_shift_hours(1260, 1800, "2025-12-30", break_6h=0, break_8h=0)
_check(
    "C-5a 21:00〜30:00 の深夜 = 420分（7h）",
    sh_c5.night_minutes == 420,
    f"got night={sh_c5.night_minutes}分",
)
_check(
    "C-5b 21:00〜30:00 の通常 = 120分（21:00〜22:00 と 翌5:00〜翌6:00 の合算）",
    sh_c5.regular_minutes == 120,
    f"got regular={sh_c5.regular_minutes}分"
    "（翌5:00以降の60分が深夜に飲み込まれている）",
)
# 金額根拠: 深夜 7h × ¥1,875 = ¥13,125 / 基本 2h × ¥1,500 = ¥3,000 → 合計 ¥16,125
# 現状は 深夜 8h × ¥1,875 = ¥15,000 / 基本 1h × ¥1,500 = ¥1,500 → ¥16,500。¥375 の過払い。
pay_c5 = calculate_daily_pay(sh_c5, hourly_rate=HOURLY, night_rate=NIGHT,
                             transport=0, role="Dealer")
_check(
    "C-5c 21:00〜30:00 の賃金 = ¥16,125（深夜¥13,125 + 基本¥3,000）",
    pay_c5.night_pay == 13125 and pay_c5.base_pay == 3000,
    f"got 深夜¥{pay_c5.night_pay} + 基本¥{pay_c5.base_pay} = "
    f"¥{pay_c5.night_pay + pay_c5.base_pay}（正しくは ¥16,125）",
)

# 深夜窓の定数が SPEC と一致しているかの参考表示（判定はしない）
print(f"     ・深夜窓の定義: {NIGHT_WINDOW_START}分(22:00) 〜 {NIGHT_WINDOW_END}分(翌5:00) "
      f"= {NIGHT_WINDOW_END - NIGHT_WINDOW_START}分")


# ============================================================
# (D) 境界値の回帰ガード（現状すべて正しい。修正で壊さないこと）
# ============================================================
print("\n[D] 境界値（現状OK・回帰防止）")

# --- D-1: 22:00 ちょうどに終わるシフトは深夜0分 ---
# 13:00〜22:00。total = 1320 - 780 = 540分（9時間）→ 8時間超なので休憩60分。
# 通常 = 540 - 60 = 480分（8時間）、深夜 = 0分。
# 「22:00 以降」が深夜なので、22:00 ちょうどの退勤に深夜割増は付かない。
sh_d1 = calculate_shift_hours(780, 1320, "2025-12-29")
_check(
    "D-1a 22:00 ちょうど退勤は深夜 0分",
    sh_d1.night_minutes == 0,
    f"got night={sh_d1.night_minutes}分",
)
_check(
    "D-1b 13:00〜22:00 の通常 = 480分（9h - 休憩60分）",
    sh_d1.regular_minutes == 480,
    f"got regular={sh_d1.regular_minutes}分",
)
# 金額根拠: 8h × ¥1,500 = ¥12,000 / 深夜 ¥0
pay_d1 = calculate_daily_pay(sh_d1, hourly_rate=HOURLY, night_rate=NIGHT,
                             transport=0, role="Dealer")
_check(
    "D-1c 13:00〜22:00 の賃金 = 基本¥12,000 + 深夜¥0",
    pay_d1.base_pay == 12000 and pay_d1.night_pay == 0,
    f"got 基本¥{pay_d1.base_pay} / 深夜¥{pay_d1.night_pay}",
)

# --- D-2/D-3/D-4: 休憩の境界（6時間ちょうど / 8時間ちょうど / 8時間超） ---
# 労基法: 6時間「超」で45分、8時間「超」で60分。ちょうどは下の階段に留まる。
_check("D-2 6時間ちょうど（360分）は休憩0分",
       calculate_break_minutes(6 * 60) == 0,
       f"got {calculate_break_minutes(6 * 60)}分")
_check("D-3a 6時間+1分（361分）は休憩45分",
       calculate_break_minutes(6 * 60 + 1) == 45,
       f"got {calculate_break_minutes(6 * 60 + 1)}分")
_check("D-3b 8時間ちょうど（480分）は休憩45分（8時間『超』ではない）",
       calculate_break_minutes(8 * 60) == 45,
       f"got {calculate_break_minutes(8 * 60)}分")
_check("D-4 8時間+1分（481分）は休憩60分",
       calculate_break_minutes(8 * 60 + 1) == 60,
       f"got {calculate_break_minutes(8 * 60 + 1)}分")

# --- D-5: 実働0分（出勤 == 退勤）は「不正」ではなく正当な0分 ---
# (A) の 退勤<出勤 とは意味が違う。0分勤務は0円が正しく、エラーにしてはいけない。
# 修正時に total <= 0 をまとめて例外にすると、ここが巻き添えで壊れる。
sh_d5 = calculate_shift_hours(780, 780, "2025-12-29")
_check(
    "D-5a 出勤==退勤（実働0分）は例外にせず 0分を返す",
    sh_d5 is not None and sh_d5.total_minutes == 0,
    f"got {sh_d5!r}",
)
_check(
    "D-5b 実働0分の通常・深夜・休憩はすべて0分",
    sh_d5.regular_minutes == 0 and sh_d5.night_minutes == 0
    and sh_d5.break_minutes == 0,
    f"got regular={sh_d5.regular_minutes} / night={sh_d5.night_minutes} "
    f"/ break={sh_d5.break_minutes}",
)

# --- D-6: 端数切り上げ 100 / 500 / 1000 ---
# round_amount は「切り上げ」。割り切れる場合はそのまま返す。
# 23,450 → 100単位: 23,450 % 100 = 50 ≠ 0 → (234+1)*100 = 23,500
#        → 500単位: 23,450 % 500 = 450 ≠ 0 → (46+1)*500 = 23,500
#        → 1000単位: 23,450 % 1000 = 450 ≠ 0 → (23+1)*1000 = 24,000
_check("D-6a 端数切り上げ 100単位: ¥23,450 → ¥23,500",
       round_amount(23450, 100) == 23500, f"got ¥{round_amount(23450, 100)}")
_check("D-6b 端数切り上げ 500単位: ¥23,450 → ¥23,500",
       round_amount(23450, 500) == 23500, f"got ¥{round_amount(23450, 500)}")
_check("D-6c 端数切り上げ 1000単位: ¥23,450 → ¥24,000",
       round_amount(23450, 1000) == 24000, f"got ¥{round_amount(23450, 1000)}")
# 割り切れるケースは切り上げない（1単位ぶん上に飛ばさない）
_check("D-6d ちょうど ¥23,500 は 100単位でも据え置き",
       round_amount(23500, 100) == 23500, f"got ¥{round_amount(23500, 100)}")
_check("D-6e ちょうど ¥24,000 は 1000単位でも据え置き",
       round_amount(24000, 1000) == 24000, f"got ¥{round_amount(24000, 1000)}")


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
