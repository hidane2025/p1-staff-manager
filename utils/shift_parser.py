"""P1 Staff Manager — シフト表CSV/TSVパーサー"""

import pandas as pd
import io
import re
from typing import Optional


def detect_role(role_str: str) -> str:
    """役職文字列を正規化"""
    if not role_str:
        return "Dealer"
    r = role_str.strip().upper()
    role_map = {
        "TD": "TD",
        "FLOOR": "Floor",
        "DC": "DC",
        "CHIP": "Chip",
        "DEALER": "Dealer",
        "チップ": "Chip",
        "フロア": "Floor",
        "ディーラー": "Dealer",
        "シフトリーダー": "Floor",
        "シフト補佐": "Floor",
        "中国ディーラー": "Dealer",
    }
    for key, val in role_map.items():
        if key in r:
            return val
    return "Dealer"


_ZENKAKU_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def normalize_digits(s: str) -> str:
    """全角数字を半角に正規化"""
    return str(s).translate(_ZENKAKU_DIGITS)


def safe_int(v, default: int = 0) -> int:
    """全角/半角混在にも強い整数変換"""
    if v is None:
        return default
    s = normalize_digits(str(v).strip())
    if not s:
        return default
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return default


def parse_time_cell(cell_value) -> Optional[str]:
    """セルの時刻文字列をパース。×やNaNはNone"""
    if pd.isna(cell_value):
        return None
    val = normalize_digits(str(cell_value).strip())
    if val in ("", "×", "x", "X", "-", "ー", "—"):
        return None
    return val


def detect_date_columns(columns: list) -> list:
    """日付っぽいカラムを検出"""
    date_cols = []
    for col in columns:
        col_str = str(col).strip()
        # 12/29(月), 1/2(金), 2025-12-29, etc.
        if re.search(r'\d{1,2}/\d{1,2}', col_str) or re.search(r'\d{4}-\d{2}-\d{2}', col_str):
            date_cols.append(col)
    return date_cols


def normalize_date(col_name: str, year: int = 2025, ref_month: int = 0) -> str:
    """カラム名から日付文字列を生成

    '12/29(月)' → '2025-12-29'
    '1/2(金)' → '2026-01-02'

    ref_month: 最初の日付の月。0なら自動判定。
    年跨ぎ判定: 最初の月より小さい月が出たら翌年とみなす。
    """
    col_str = str(col_name).strip()
    match = re.search(r'(\d{1,2})/(\d{1,2})', col_str)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        if ref_month > 0 and month < ref_month:
            actual_year = year + 1
        else:
            actual_year = year
        return f"{actual_year}-{month:02d}-{day:02d}"

    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', col_str)
    if match:
        return match.group(0)

    return col_str


def parse_shift_csv(file_content: bytes, year: int = 2025) -> dict:
    """CSVまたはTSVのシフト表をパース

    Returns:
        {
            "staff": [{"no": 18, "name_jp": "EveKat", "name_en": "EVEKAT", "role": "Dealer"}, ...],
            "dates": ["2025-12-29", ...],
            "shifts": [
                {"no": 18, "name_jp": "EveKat", "role": "Dealer",
                 "date": "2025-12-29", "time_range": "13:00~22:00"},
                ...
            ]
        }
    """
    text = file_content.decode("utf-8", errors="replace")

    # TSVかCSVか判定
    if "\t" in text.split("\n")[0]:
        df = pd.read_csv(io.StringIO(text), sep="\t", header=0, dtype=str)
    else:
        df = pd.read_csv(io.StringIO(text), header=0, dtype=str)

    # カラム名の前後空白を除去
    df.columns = [str(c).strip() for c in df.columns]

    # 役職・NO.・名前のカラムを検出
    role_col = None
    no_col = None
    name_jp_col = None
    name_en_col = None

    for col in df.columns:
        col_lower = col.lower()
        if col_lower in ("役職", "role", "ポジション"):
            role_col = col
        elif col_lower in ("no.", "no", "番号", "#"):
            no_col = col
        elif col_lower in ("名前", "name_jp", "ディーラーネーム", "名前（日本語）"):
            name_jp_col = col
        elif col_lower in ("name", "name_en", "英名"):
            name_en_col = col

    # カラムが見つからない場合のフォールバック
    if role_col is None and len(df.columns) > 0:
        role_col = df.columns[0]
    if no_col is None and len(df.columns) > 2:
        no_col = df.columns[2]
    if name_jp_col is None and len(df.columns) > 3:
        name_jp_col = df.columns[3]
    if name_en_col is None and len(df.columns) > 4:
        name_en_col = df.columns[4]

    date_cols = detect_date_columns(df.columns)
    # 最初の日付の月を検出して年跨ぎ判定に使う
    first_month = 0
    if date_cols:
        m = re.search(r'(\d{1,2})/', str(date_cols[0]))
        if m:
            first_month = int(m.group(1))
    dates = [normalize_date(col, year, ref_month=first_month) for col in date_cols]

    staff_list = []
    shift_list = []
    seen_staff = set()

    for _, row in df.iterrows():
        name_jp = str(row.get(name_jp_col, "")).strip() if name_jp_col else ""
        if not name_jp or name_jp == "nan":
            continue

        role_raw = str(row.get(role_col, "")).strip() if role_col else ""
        role = detect_role(role_raw)
        no_raw = row.get(no_col, "") if no_col else ""
        no = safe_int(no_raw, 0)

        name_en = str(row.get(name_en_col, "")).strip() if name_en_col else ""
        if name_en == "nan":
            name_en = ""

        staff_key = (no, name_jp)
        if staff_key not in seen_staff:
            seen_staff.add(staff_key)
            staff_list.append({
                "no": no,
                "name_jp": name_jp,
                "name_en": name_en,
                "role": role,
            })

        for col, date in zip(date_cols, dates):
            time_val = parse_time_cell(row.get(col))
            if time_val:
                shift_list.append({
                    "no": no,
                    "name_jp": name_jp,
                    "role": role,
                    "date": date,
                    "time_range": time_val,
                })

    return {
        "staff": staff_list,
        "dates": dates,
        "shifts": shift_list,
    }
