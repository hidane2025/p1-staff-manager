"""勤務時刻の入力粒度を1箇所で決める（2026-08-07）

背景:
    退勤・遅刻・早退・延長などの「分」の選択肢が、ピット端末と出退勤ページの
    計7箇所に [0, 15, 30, 45] とベタ書きされていた。15分きざみだと実際の
    上がり時刻（例 22:47）を記録できず、最大13分ぶんの丸めが支払額に乗る。
    粒度はここだけで決める（画面ごとに違う刻みになる事故を防ぐ）。

方針:
    5分きざみ。1人1日あたりの誤差は最大2分（時給1,500円で約50円）に収まる。
    運用上15分きざみに戻したくなった場合は STEP_MINUTES を 15 にするだけでよい。
"""

from __future__ import annotations

STEP_MINUTES = 5

# 選択肢（0, 5, 10, … 55）
MINUTE_CHOICES: list = list(range(0, 60, STEP_MINUTES))

# 「時」の入力範囲。深夜跨ぎを 24 時超えで表すため 29 まで許す（29:00＝翌5時）
HOUR_MIN = 0
HOUR_MAX = 29


def snap_minute(minute: int) -> int:
    """任意の分を選択肢に丸める（切り捨て）。範囲外は 0 にする。"""
    try:
        m = int(minute)
    except (TypeError, ValueError):
        return 0
    if m < 0 or m > 59:
        return 0
    return (m // STEP_MINUTES) * STEP_MINUTES


def minute_index(minute: int) -> int:
    """selectbox の index を返す（丸めた上で位置を引く）。"""
    return MINUTE_CHOICES.index(snap_minute(minute))


def split_hhmm(value, default_hour: int = 0, default_minute: int = 0) -> tuple:
    """'HH:MM'（24時超え可）を (時, 丸めた分) に分解する。失敗時は既定値。"""
    try:
        h, m = str(value).split(":")
        hour = max(HOUR_MIN, min(HOUR_MAX, int(h)))
        return hour, snap_minute(int(m))
    except (ValueError, AttributeError, TypeError):
        return default_hour, snap_minute(default_minute)


# ============================================================
# 一覧の直接編集で使う「時刻プルダウン」とその正規化（2026-08-16 集約）
#   出退勤ページ・支払い計算ページに同じ選択肢生成と正規化が
#   別々に書かれていた（刻み・上限がズレると支払額の丸めが画面で変わる）。
#   振る舞いは従来と同一（7:00〜29:55 の5分刻み＋30:00、"—"=未記録）。
# ============================================================
EMPTY_TIME = "—"
_EDIT_HOUR_MIN = 7
_EDIT_HOUR_MAX = 29

# 実到着・実退勤の選択肢（先頭は「—」＝未記録/取り消し）
TIME_OPTIONS: list = (
    [EMPTY_TIME]
    + [f"{h:02d}:{m:02d}"
       for h in range(_EDIT_HOUR_MIN, _EDIT_HOUR_MAX + 1)
       for m in range(0, 60, STEP_MINUTES)]
    + ["30:00"]
)


def normalize_edit_time(value) -> tuple:
    """一覧に入力された時刻を正規化する。

    Returns:
        (正規化済み "HH:MM" or None, 妥当か bool)
        "—"・空文字は (None, True)＝未記録。読めない値・0〜48時間外は (None, False)。
    """
    from utils.calculator import parse_time_to_minutes

    v = str(value or "").strip()
    if v in ("", EMPTY_TIME, "-", "ー", "None"):
        return None, True
    m = parse_time_to_minutes(v)
    if m is None or not (0 <= m < 48 * 60):
        return None, False
    return f"{m // 60:02d}:{m % 60:02d}", True
