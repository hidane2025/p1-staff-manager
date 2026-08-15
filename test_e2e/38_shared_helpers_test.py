"""共通ヘルパー（時刻選択肢・時刻正規化・休憩ルール）の単体テスト — DB非依存

2026-08-16 リファクタで3ページに散在していた実装を1箇所へ集約した。
「集約前と同じ振る舞い」を固定し、画面ごとに刻み・上限・判定がズレる事故を防ぐ。
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from utils.time_input import (  # noqa: E402
    TIME_OPTIONS, EMPTY_TIME, STEP_MINUTES, normalize_edit_time,
)
from utils.roles import break_minutes_for  # noqa: E402

failures: list = []


def _check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + ("" if cond else f" — {detail}"))
    if not cond:
        failures.append(name)


print("[A] 時刻プルダウンの選択肢（集約前と完全一致）")
_legacy = ["—"] + [f"{h:02d}:{m:02d}" for h in range(7, 30)
                   for m in range(0, 60, 5)] + ["30:00"]
_check("集約前の生成結果と同一", TIME_OPTIONS == _legacy,
       f"{len(TIME_OPTIONS)} vs {len(_legacy)}")
_check("先頭は未記録マーカー", TIME_OPTIONS[0] == EMPTY_TIME)
_check("末尾は30:00（大会の最終退勤）", TIME_OPTIONS[-1] == "30:00")
_check("刻みは5分", STEP_MINUTES == 5 and "07:05" in TIME_OPTIONS
       and "07:01" not in TIME_OPTIONS)
_check("24時超表記を含む（深夜退勤）", "25:30" in TIME_OPTIONS and "29:55" in TIME_OPTIONS)
_check("7時前は選べない（前日の打刻誤りを防ぐ）", "06:55" not in TIME_OPTIONS)

print("[B] 時刻の正規化")
for v in ("—", "", "-", "ー", "None", None):
    _check(f"未記録扱い: {v!r}", normalize_edit_time(v) == (None, True))
_check("通常時刻", normalize_edit_time("09:30") == ("09:30", True))
_check("24時超", normalize_edit_time("25:30") == ("25:30", True))
_check("30:00は妥当", normalize_edit_time("30:00") == ("30:00", True))
_check("48h以上は不正", normalize_edit_time("48:00") == (None, False))
_check("読めない値は不正", normalize_edit_time("あ") == (None, False))
_check("前後の空白は許容", normalize_edit_time(" 10:00 ") == ("10:00", True))

print("[C] 休憩控除ルール（受付系のみ）")
_check("受付は控除あり", break_minutes_for("受付", 45, 60) == (45, 60))
for r in ("Dealer", "Floor", "TD", "Pit", "Chip", "DC"):
    _check(f"{r} は控除なし", break_minutes_for(r, 45, 60) == (0, 0))
_check("未知役職は受付系扱い＝控除あり（role_dept準拠）",
       break_minutes_for("なんとか係", 45, 60) == (45, 60))
_check("イベント側が0なら受付でも0", break_minutes_for("受付", 0, 0) == (0, 0))

print("[D] 集約先が1箇所であること（重複定義の再発防止）")
_pages = list((ROOT / "pages").glob("*.py"))
_dup_opts = [f.name for f in _pages if "range(7, 30)" in f.read_text()]
_check("時刻選択肢のベタ書きがページに無い", not _dup_opts, str(_dup_opts))
_dup_dept = [f.name for f in _pages
             if re.search(r'role_dept\([^)]*\)\s*(==|!=)\s*"受付系"', f.read_text())]
_check("休憩判定のベタ書きがページに無い", not _dup_dept, str(_dup_dept))
_calc = (ROOT / "utils/calculator.py").read_text()
_check("calculatorも共通関数を使う", "break_minutes_for" in _calc)

print("=" * 60)
if failures:
    print(f"❌ 失敗 {len(failures)}件")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✅ 全テスト成功")
