"""2026-08-09〜08-12 の変更を固定する回帰テスト（DB・Streamlit 非依存）

対象:
  A. utils/shift_parser — 見出し行の自動検出・列推定・括弧つき時刻・除外NO.・警告
     （8月大阪の確定シフト表が「日付列0件→シフト0件」で丸ごと落ちていた事故の再発防止）
  B. utils/transport_rules.payment_amount — ピット端末と支払い計算の交通費判定の一元化
     （遠方スタッフにピットだけ日額を過大加算＝54名・269,000円の表示差の再発防止）
  C. utils/calculator — 日当の対象役職（Floor だけ→ Floor/TD/Pit/Chip）
  D. dbx/staff.find_or_create_staff — NO. 優先の同定
     （NO.79 と NO.510 の同名「Aoi」が1人に統合され勤務が消えた事故の再発防止）
  E. ソース配線 — viewer 開放は出退勤のみ／役職リストは utils/roles.py に一元化
"""
from __future__ import annotations

import csv
import io
import pathlib
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

failures: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name}" + ("" if cond else f" — {detail}"))
    if not cond:
        failures.append(name)


# ============================================================
# A. shift_parser
# ============================================================
print("\n[A] shift_parser（確定シフト表の形をそのまま食わせる）")
from utils.shift_parser import (  # noqa: E402
    parse_shift_csv, detect_role, normalize_time_cell, detect_header_row,
    guess_columns,
)


def _csv(rows: list[list]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode("utf-8")


SHEET = [
    ["P1 CIRCUIT テスト大会 個人別シフト一覧", "", "", "", "", "", "", "", ""],
    ["このタブはシフト表に数式連動しています", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", ""],
    ["No", "配置", "番号", "活動名義", "通勤/宿泊", "採用優先", "メモ",
     "8/12(水)", "8/13(木)"],
    ["1", "DEALER", "79", "Aoi", "ホテル", "", "", "9:30-18:30\n(19:30)", "×"],
    ["2", "DEALER", "510", "Aoi", "通勤", "", "", "10:00-17:00", "休"],
    ["3", "FLOOR", "323", "ena", "通勤", "", "", "15:00-25:00", "15:00~25:00"],
    ["4", "PIT", "18", "EveKat", "ホテル", "", "", "12:00-22:00", "abc-def"],
    ["5", "DEALER", "1007", "Min Ji", "ホテル", "", "", "12:00-22:00", "12:00-22:00"],
    ["6", "TD", "", "Eden", "ホテル", "通常/遠方", "", "", ""],
    ["7", "DEALER", "60", "キョウ", "通勤", "", "", "20:00-26:00", ""],
    ["8", "DEALER", "61", "偽キョウ", "通勤", "", "", "", "9:00-15:00"],
]

raw = _csv(SHEET)
rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
_check("見出し行を自動検出（先頭タイトル2行を飛ばして3行目=index3）",
       detect_header_row(rows) == 3, str(detect_header_row(rows)))
g = guess_columns(rows[3])
_check("「配置」を役職・「番号」をNO.・「活動名義」を名前と推定",
       g.get("role") == "配置" and g.get("no") == "番号" and g.get("name_jp") == "活動名義", str(g))
_check("「通勤/宿泊」を英名として誤推定しない", g.get("name_en") != "通勤/宿泊", str(g))

p = parse_shift_csv(raw, year=2026, exclude_nos=[1007])
_check("日付2列を 2026-08-12 / 2026-08-13 に正規化",
       p["dates"] == ["2026-08-12", "2026-08-13"], str(p["dates"]))
_check("除外NO.(1007)が excluded に入り取り込まれない",
       len(p["excluded"]) == 1 and p["excluded"][0]["name_jp"] == "Min Ji"
       and all(s["no"] != 1007 for s in p["shifts"]), str(p["excluded"]))
_check("読めないセル(abc-def)が skipped に理由つきで出る",
       len(p["skipped"]) == 1 and p["skipped"][0]["name_jp"] == "EveKat"
       and p["skipped"][0]["reason"], str(p["skipped"]))
_check("×・休・空欄はエラーにしない（skippedに入らない）",
       all(s["raw"] not in ("×", "休", "") for s in p["skipped"]))
_check("同名別NO.（Aoi×2）が警告される",
       any("Aoi" in w and "2人" in w for w in p["warnings"]), str(p["warnings"]))
_check("NO.空欄（Eden）が警告される",
       any("空欄" in w for w in p["warnings"]), str(p["warnings"]))
_check("PIT の役職が Pit になる（Dealer に丸めない）",
       any(s["role"] == "Pit" for s in p["staff"] if s["name_jp"] == "EveKat"),
       str([s for s in p["staff"] if s["name_jp"] == "EveKat"]))
_aoi = [s for s in p["shifts"] if s["name_jp"] == "Aoi"]
_check("括弧つきセルは既定で手前の時刻（9:30~18:30）",
       any(s["time_range"] == "9:30~18:30" for s in _aoi), str(_aoi))
_check("括弧セルが paren_cells に記録される（84件消失事故の可視化）",
       len(p["paren_cells"]) == 1 and p["paren_cells"][0]["paren_end"] == "19:30",
       str(p["paren_cells"]))
p2 = parse_shift_csv(raw, year=2026, paren_mode="paren")
_aoi2 = [s for s in p2["shifts"] if s["no"] == 79]
_check("paren_mode='paren' なら括弧の時刻を終了に採用（9:30~19:30）",
       any(s["time_range"] == "9:30~19:30" for s in _aoi2), str(_aoi2))

nt = normalize_time_cell("9:30-18:30\n(19:30)")
_check("normalize_time_cell: 改行＋括弧を分解", nt[0] == "9:30~18:30" and nt[1] == "19:30", str(nt))
_check("normalize_time_cell: 全角チルダ・２５時表記も通る",
       normalize_time_cell("15:00～25:00")[0] == "15:00~25:00")
_check("detect_role: ピット表記ゆれ",
       detect_role("PIT") == "Pit" and detect_role("ピット") == "Pit"
       and detect_role("HD/TD") == "TD")

# ============================================================
# B. transport_rules.payment_amount
# ============================================================
print("\n[B] transport_rules.payment_amount（ピット⇔支払い計算の一元判定）")
from utils.transport_rules import payment_amount  # noqa: E402

RULES = {
    "近畿": {"region": "近畿", "max_amount": 1000, "receipt_required": 0, "is_venue_region": 1},
    "東海": {"region": "東海", "max_amount": 15000, "receipt_required": 1, "is_venue_region": 0},
}
amt, why = payment_amount(RULES, "近畿", 5, None)
_check("開催地: 日額×日数（1,000×5=5,000）", amt == 5000, f"{amt} / {why}")
amt, why = payment_amount(RULES, "東海", 5, None)
_check("遠方・領収書なし → 0円（日額を勝手に積まない）", amt == 0, f"{amt} / {why}")
amt, why = payment_amount(RULES, "東海", 5, {"has_receipt": 1, "approved_amount": 12000})
_check("遠方・領収書あり → 承認額", amt == 12000, f"{amt} / {why}")
amt, why = payment_amount(RULES, None, 5, None)
_check("地域未登録 → 0円＋理由", amt == 0 and why, f"{amt} / {why}")
amt, why = payment_amount({}, "東海", 5, None)
_check("ルール未設定 → None（旧ロジックへ委譲）", amt is None, f"{amt} / {why}")

# ============================================================
# C. calculator — 日当の対象役職
# ============================================================
print("\n[C] calculator（日当 Floor/TD/Pit/Chip）")
from utils.calculator import calculate_shift_hours, calculate_daily_pay  # noqa: E402

sh = calculate_shift_hours(9 * 60, 19 * 60, "2026-08-12", break_6h=0, break_8h=0)
for role, expect in (("Floor", 3000), ("TD", 3000), ("Pit", 3000), ("Chip", 3000),
                     ("Dealer", 0), ("DC", 0)):
    d = calculate_daily_pay(sh, 1500, 1875, transport=0, role=role, floor_bonus=3000)
    _check(f"{role} の日当 = ¥{expect:,}", d.floor_bonus == expect, str(d.floor_bonus))

print("\n[C2] 精勤手当の対象役職（受付には付けない）")
from utils.calculator import calculate_staff_payment  # noqa: E402

_rates = {f"2026-08-{d}": {"hourly": 1500, "night": 1875, "transport": 0,
                           "floor_bonus": 3000, "mix_bonus": 1500} for d in range(12, 17)}
_shifts5 = [{"date": f"2026-08-{d}", "start": "10:00", "end": "18:00", "is_mix": False}
            for d in range(12, 17)]
_pd = calculate_staff_payment(staff_id=1, name="D", role="Dealer", shifts=_shifts5,
                              rates_by_date=_rates, total_event_days=5,
                              break_6h=45, break_8h=60, transport_override=0)
_pr = calculate_staff_payment(staff_id=2, name="R", role="受付", shifts=_shifts5,
                              rates_by_date=_rates, total_event_days=5,
                              break_6h=45, break_8h=60, transport_override=0)
_check("Dealer 全日出勤 → 精勤手当 ¥10,000", _pd.attendance_bonus == 10000,
       str(_pd.attendance_bonus))
_check("受付 全日出勤 → 精勤手当 ¥0（対象外役職）", _pr.attendance_bonus == 0,
       str(_pr.attendance_bonus))
_check("受付に日当も付かない", _pr.floor_bonus_total == 0, str(_pr.floor_bonus_total))
_pc = calculate_staff_payment(staff_id=3, name="C", role="受付", shifts=_shifts5,
                              rates_by_date=_rates, total_event_days=5,
                              break_6h=45, break_8h=60, transport_override=0,
                              custom_hourly_rate=1350)
# 10:00-18:00 = 拘束8h → 休憩45分 → 実働7.25h。日次で丸めて 9,788×5
_check("個別時給1,350の基本給（7.25h×1350を日次丸め×5日）",
       _pc.base_pay == round(7.25 * 1350) * 5, str(_pc.base_pay))
_shift_n = [{"date": "2026-08-12", "start": "22:00", "end": "23:00", "is_mix": False}]
_pn = calculate_staff_payment(staff_id=4, name="N", role="受付", shifts=_shift_n,
                              rates_by_date=_rates, total_event_days=5,
                              break_6h=45, break_8h=60, transport_override=0,
                              custom_hourly_rate=1350)
_check("個別時給の深夜は×1.25を整数化（1350→1688/h）", _pn.night_pay == 1688, str(_pn.night_pay))

# ============================================================
# D. find_or_create_staff — NO. 優先の同定
# ============================================================
print("\n[D] find_or_create_staff（同名別NO.を統合しない）")
import dbx.staff as staff_mod  # noqa: E402


class _FakeQ:
    def __init__(self, rows):
        self._rows = rows
        self._f = []

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._f.append((col, val))
        return self

    def execute(self):
        rows = self._rows
        for c, v in self._f:
            rows = [r for r in rows if r.get(c) == v]
        return SimpleNamespace(data=rows)


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        return _FakeQ(self._rows if name == "p1_staff" else [])


_orig_get_client = staff_mod.core.get_client
_orig_create = staff_mod.create_staff
_created: list[tuple] = []
staff_mod.core.get_client = lambda: _FakeClient([{"id": 1, "no": 79, "name_jp": "Aoi"}])
staff_mod.create_staff = lambda no, nj, ne="", role="Dealer": (_created.append((no, nj)) or 999)
try:
    _check("NO.一致 → 既存を返す（作成しない）",
           staff_mod.find_or_create_staff(79, "Aoi") == 1 and not _created, str(_created))
    _created.clear()
    r = staff_mod.find_or_create_staff(510, "Aoi")
    _check("NO.違いの同名 → 名前で吸収せず新規作成（Aoi事故の再発防止）",
           r == 999 and _created == [(510, "Aoi")], f"r={r} created={_created}")
    _created.clear()
    _check("NO.なし・同名あり → 名前で既存を返す",
           staff_mod.find_or_create_staff(None, "Aoi") == 1 and not _created, str(_created))
    _created.clear()
    _check("NO.なし・未知名 → 新規作成",
           staff_mod.find_or_create_staff(0, "新規さん") == 999 and _created == [(0, "新規さん")],
           str(_created))
finally:
    staff_mod.core.get_client = _orig_get_client
    staff_mod.create_staff = _orig_create

# ============================================================
# E. ソース配線
# ============================================================
print("\n[E] ソース配線（viewer 開放・役職一元化・交通費一元化）")
_att = (ROOT / "pages/5_attendance.py").read_text()
_check("出退勤は viewer を許可", 'roles=("admin", "viewer")' in _att)
_check("出退勤の更新ボタンは全て viewer で無効化（button数=disabled数）",
       _att.count("st.button(") == _att.count("disabled=_READONLY"),
       f"button={_att.count('st.button(')} disabled={_att.count('disabled=_READONLY')}")
# 「viewer が入室できる」＝ require_admin の roles= に viewer を含む場合のみ。
# （95_users.py は権限選択肢の文言として "viewer" を含むが入室許可ではない）
_viewer_pages = sorted(f.name for f in (ROOT / "pages").glob("*.py")
                       if 'roles=("admin", "viewer")' in f.read_text())
_check("viewer を許可するページは出退勤の1枚だけ",
       _viewer_pages == ["5_attendance.py"], str(_viewer_pages))
_pit = (ROOT / "pages/10_pit_terminal.py").read_text()
_check("ピット端末の交通費は payment_amount 経由",
       "transport_rules_mod.payment_amount" in _pit)
_check("支払い計算の交通費も payment_amount 経由",
       "transport_rules_mod.payment_amount" in (ROOT / "pages/3_payment.py").read_text())
from utils.roles import CANONICAL_ROLES, DAY_ALLOWANCE_ROLES  # noqa: E402
_check("役職の正準リストに Pit が含まれる", "Pit" in CANONICAL_ROLES, str(CANONICAL_ROLES))
_check("役職の正準リストに 受付 が含まれる", "受付" in CANONICAL_ROLES, str(CANONICAL_ROLES))
from utils.roles import role_dept, DEPT_CHOICES  # noqa: E402
_check("部門判定: 受付→受付系・Dealer/TD→ディーラー系",
       role_dept("受付") == "受付系" and role_dept("Dealer") == "ディーラー系"
       and role_dept("TD") == "ディーラー系" and role_dept(None) == "ディーラー系")
_check("出退勤に部門フィルタがあり一括操作より前に効く",
       "attend_dept" in (ROOT / "pages/5_attendance.py").read_text())
_check("封筒に部門フィルタがある",
       "env_dept" in (ROOT / "pages/4_envelope.py").read_text())
_check("日当対象は Floor/TD/Pit/Chip",
       set(DAY_ALLOWANCE_ROLES) == {"Floor", "TD", "Pit", "Chip"}, str(DAY_ALLOWANCE_ROLES))
import utils.calculator as _calc  # noqa: E402
_check("calculator は roles.py の定義を共有（同一オブジェクト）",
       _calc.DAY_ALLOWANCE_ROLES is DAY_ALLOWANCE_ROLES)
for pg in ("pages/1_staff.py", "pages/3_payment.py", "pages/5_attendance.py"):
    src = (ROOT / pg).read_text()
    _check(f"{pg} は役職リストをハードコードしない",
           '"Dealer", "Floor", "TD"' not in src and "CANONICAL_ROLES" in src)

# ============================================================
print()
print("=" * 60)
if failures:
    print(f"❌ 失敗 {len(failures)}件:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✅ 全テスト成功")
