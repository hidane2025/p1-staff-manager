"""P1 Staff Manager — シフト表CSV/TSVパーサー

2026-08-09 改修（8月大阪の確定シフト表を取り込めるようにした）:
  - 見出し行の自動検出。表の上にタイトル・注記が乗っていても読める
    （従来は1行目を見出しと決め打ちし、日付列を1つも見つけられず
      シフトが丸ごと0件になっていた）
  - 列名の候補を拡張（配置 / 活動名義 など）＋ 呼び出し側から明示指定可能
  - 括弧つき時刻 `12:00-21:00 (22:00)` と改行入りセルを正規化
  - 読めなかったセルを skipped に、NO.重複・欠番を warnings に返す
    （黙って落とさない。取込画面が一覧で見せる）
"""

import pandas as pd
import io
import re
from typing import Optional

try:
    from utils.calculator import parse_shift_time
except ImportError:  # 単体実行・パス構成違いのフォールバック
    from calculator import parse_shift_time


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
        # PIT は 2026-08-09 まで未定義で Dealer に丸められ、日当3,000円が
        # 付かなかった（P1の単価ルールでは PIT も日当の対象）。
        "PIT": "Pit",
        "ピット": "Pit",
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


# 休み・空欄を表す記号（この表記は取り込まないが、エラーでもない）
_BLANK_CELLS = ("", "nan", "none", "×", "x", "-", "ー", "—", "休", "休み", "off", "0")


def parse_time_cell(cell_value) -> Optional[str]:
    """セルの時刻文字列をパース。×やNaNはNone（後方互換のため残す）"""
    if pd.isna(cell_value):
        return None
    val = normalize_digits(str(cell_value).strip())
    if val.lower() in _BLANK_CELLS:
        return None
    return val


_DATE_PAT = re.compile(r"\d{1,2}\s*/\s*\d{1,2}|\d{4}-\d{2}-\d{2}")
# 括弧つきの補助時刻: 「(22:00)」「（29:00）」
_PAREN_PAT = re.compile(r"[（(]\s*(\d{1,2}\s*[:：]\s*\d{2})\s*[)）]")
# 時刻レンジ本体。区切りは calculator.parse_shift_time と同じ揺れを許容
_RANGE_PAT = re.compile(
    r"(\d{1,2}:\d{2})\s*[-~〜～ー－−–—|｜]\s*(\d{1,2}:\d{2})"
)


def _date_like(cell) -> bool:
    return bool(_DATE_PAT.search(str(cell or "")))


def detect_date_columns(columns: list) -> list:
    """日付っぽいカラムを検出"""
    return [c for c in columns if _date_like(c)]


def detect_header_row(rows: list, max_scan: int = 20) -> int:
    """日付らしきセルが最も多い行を見出し行とみなす。

    シフト表は上部にタイトル・注記・空行が入ることが多い。見出しを決め打ちすると
    日付列が1つも見つからず、シフトが丸ごと0件になる（2026-08 実測）。
    候補が無ければ 0（従来どおり先頭行）を返す。
    """
    best, best_n = 0, 0
    for i, row in enumerate(rows[:max_scan]):
        n = sum(1 for c in row if _date_like(c))
        if n > best_n:
            best, best_n = i, n
    return best


# 列の候補語。リストの前にあるものほど優先度が高い
FIELD_KEYWORDS = {
    "role": ["役職", "配置", "ポジション", "position", "role", "担当"],
    "no": ["番号", "no.", "スタッフno", "staff_no", "no", "#"],
    "name_jp": ["活動名義", "ディーラーネーム", "名前（日本語）", "名前(日本語)",
                "名前", "氏名", "表示名", "name_jp"],
    "name_en": ["名前（英）", "名前(英)", "英名", "英語名", "name_en", "name"],
}
FIELD_LABELS = {"role": "役職", "no": "NO.", "name_jp": "名前", "name_en": "英名"}


def _norm_col(c) -> str:
    return str(c).strip().lower().replace(" ", "").replace("　", "")


def guess_columns(columns: list) -> dict:
    """見出しから役職/NO./名前/英名の列を推定する。

    完全一致を先に取り、余った項目だけ部分一致で埋める。日付列は候補から外す。
    """
    date_cols = set(detect_date_columns(columns))
    cands = [c for c in columns if c not in date_cols and str(c).strip()]
    assigned, used = {}, set()

    for field, keys in FIELD_KEYWORDS.items():
        for k in keys:
            hit = next((c for c in cands
                        if c not in used and _norm_col(c) == _norm_col(k)), None)
            if hit is not None:
                assigned[field] = hit
                used.add(hit)
                break

    for field, keys in FIELD_KEYWORDS.items():
        if field in assigned:
            continue
        for k in keys:
            hit = next((c for c in cands
                        if c not in used and _norm_col(k) in _norm_col(c)), None)
            if hit is not None:
                assigned[field] = hit
                used.add(hit)
                break
    return assigned


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


def normalize_time_cell(raw, paren_mode: str = "first") -> tuple:
    """セルを 'HH:MM~HH:MM' に正規化する。

    改行入り（`9:30-18:30\\n(19:30)`）や括弧つきの補助時刻に対応する。

    paren_mode:
      "first" … 括弧を無視して手前のレンジを採る（既定）
      "paren" … 括弧内の時刻を終了時刻として採る

    Returns: (time_range or None, paren_end or None, reason)
      reason は読めなかったときだけ埋まる。休み・空欄は reason 空で None。
    """
    if raw is None or (not isinstance(raw, str) and pd.isna(raw)):
        return None, None, ""
    s = normalize_digits(str(raw)).replace("\r", " ").replace("\n", " ")
    s = s.replace("：", ":").strip()
    if s.lower() in _BLANK_CELLS:
        return None, None, ""

    m = _PAREN_PAT.search(s)
    paren_end = m.group(1).replace(" ", "").replace("：", ":") if m else None
    base = _PAREN_PAT.sub(" ", s)

    r = _RANGE_PAT.search(base.replace(" ", ""))
    if not r:
        return None, paren_end, "開始〜終了の時刻として読めない"

    start, end = r.group(1), r.group(2)
    if paren_end and paren_mode == "paren":
        end = paren_end
    time_range = f"{start}~{end}"
    if parse_shift_time(time_range) is None:
        return None, paren_end, "時刻の値が不正"
    return time_range, paren_end, ""


def _uniquify(cols: list) -> list:
    """空・重複した見出しを一意な名前にする（pandas の列指定を壊さないため）"""
    out, seen = [], {}
    for i, c in enumerate(cols):
        name = str(c).strip() or f"列{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def read_shift_table(file_content: bytes, header_row: Optional[int] = None) -> tuple:
    """CSV/TSVを読み、見出し行を決めて DataFrame を返す。

    Returns: (df, header_row, raw_rows)
    """
    text = file_content.decode("utf-8", errors="replace")
    sep = "\t" if "\t" in text.split("\n")[0] else ","
    raw = pd.read_csv(io.StringIO(text), sep=sep, header=None,
                      dtype=str, keep_default_na=False)
    rows = raw.values.tolist()
    if not rows:
        return pd.DataFrame(), 0, rows
    hr = detect_header_row(rows) if header_row is None else max(0, min(header_row, len(rows) - 1))
    cols = _uniquify(rows[hr])
    body = rows[hr + 1:]
    df = pd.DataFrame(body, columns=cols) if body else pd.DataFrame(columns=cols)
    return df, hr, rows


def parse_shift_csv(file_content: bytes, year: int = 2025,
                    header_row: Optional[int] = None,
                    mapping: Optional[dict] = None,
                    paren_mode: str = "first",
                    exclude_nos=()) -> dict:
    """CSVまたはTSVのシフト表をパース

    Args:
        header_row: 見出し行の位置（0始まり）。Noneなら自動検出
        mapping: {"role": 列名, "no": 列名, "name_jp": 列名, "name_en": 列名}
                 Noneなら見出しから推定
        paren_mode: 括弧つき時刻の扱い "first"（無視）/ "paren"（採用）
        exclude_nos: 取り込まないNO.の集合（他社管理のスタッフなど）

    Returns:
        {
            "staff": [{"no": 18, "name_jp": "EveKat", "name_en": "EVEKAT", "role": "Dealer"}, ...],
            "dates": ["2025-12-29", ...],
            "shifts": [{"no", "name_jp", "role", "date", "time_range"}, ...],
            "skipped": [{"no", "name_jp", "date", "raw", "reason"}, ...],
            "warnings": [str, ...],
            "paren_cells": [{"no", "name_jp", "date", "raw", "paren_end"}, ...],
            "excluded": [{"no", "name_jp"}, ...],
            "columns": [列名...], "header_row": int, "mapping": {...},
        }
    """
    df, hr, _rows = read_shift_table(file_content, header_row)
    if df.empty and not len(df.columns):
        return {"staff": [], "dates": [], "shifts": [], "skipped": [],
                "warnings": ["ファイルを読み取れませんでした"], "paren_cells": [],
                "excluded": [], "columns": [], "header_row": 0, "mapping": {}}

    columns = list(df.columns)
    guessed = guess_columns(columns)
    m = dict(guessed)
    if mapping:
        m.update({k: v for k, v in mapping.items() if v})

    date_cols = detect_date_columns(columns)
    # 位置フォールバック（見出しから何も取れなかった項目のみ・日付列は除外）。
    # name_en は推定できなければ空のままにする。位置で決め打ちすると
    # 「通勤/宿泊」のような別列を英名として取り込んでしまう（2026-08 実測）。
    non_date = [c for c in columns if c not in date_cols]
    for field, idx in (("role", 0), ("no", 2), ("name_jp", 3)):
        if not m.get(field) and len(non_date) > idx:
            m[field] = non_date[idx]

    role_col, no_col = m.get("role"), m.get("no")
    name_jp_col, name_en_col = m.get("name_jp"), m.get("name_en")

    first_month = 0
    if date_cols:
        mm = re.search(r'(\d{1,2})/', str(date_cols[0]))
        if mm:
            first_month = int(mm.group(1))
    dates = [normalize_date(col, year, ref_month=first_month) for col in date_cols]

    exclude = {safe_int(n, -1) for n in (exclude_nos or ())}
    staff_list, shift_list, skipped, paren_cells, excluded = [], [], [], [], []
    warnings, seen_staff = [], set()
    no_owner = {}       # NO. → 最初に使った名前（重複検知）
    dup_reported = set()
    no_missing = []

    for _, row in df.iterrows():
        name_jp = str(row.get(name_jp_col, "")).strip() if name_jp_col else ""
        if not name_jp or name_jp.lower() in ("nan", "none"):
            continue

        role_raw = str(row.get(role_col, "")).strip() if role_col else ""
        role = detect_role(role_raw)
        no = safe_int(row.get(no_col, "") if no_col else "", 0)

        if no in exclude:
            excluded.append({"no": no, "name_jp": name_jp})
            continue

        if no <= 0:
            no_missing.append(name_jp)
        elif no in no_owner and no_owner[no] != name_jp:
            if no not in dup_reported:
                warnings.append(
                    f"NO.{no} が2人に使われています（「{no_owner[no]}」と「{name_jp}」）。"
                    f"このままだと1人に統合され、片方の勤務と支払いが消えます"
                )
                dup_reported.add(no)
        else:
            no_owner.setdefault(no, name_jp)

        name_en = str(row.get(name_en_col, "")).strip() if name_en_col else ""
        if name_en.lower() in ("nan", "none"):
            name_en = ""

        staff_key = (no, name_jp)
        if staff_key not in seen_staff:
            seen_staff.add(staff_key)
            staff_list.append({"no": no, "name_jp": name_jp,
                               "name_en": name_en, "role": role})

        for col, date in zip(date_cols, dates):
            raw = row.get(col)
            time_range, paren_end, reason = normalize_time_cell(raw, paren_mode)
            if time_range:
                shift_list.append({"no": no, "name_jp": name_jp, "role": role,
                                   "date": date, "time_range": time_range})
                if paren_end:
                    paren_cells.append({"no": no, "name_jp": name_jp, "date": date,
                                        "raw": str(raw).replace("\n", " ").strip(),
                                        "paren_end": paren_end})
            elif reason:
                skipped.append({"no": no, "name_jp": name_jp, "date": date,
                                "raw": str(raw).replace("\n", " ").strip(),
                                "reason": reason})

    # 同名・別NO. は「別人」か「NO.の付け替え」かを機械では決められない。
    # どちらでも支払いに直結するので、取り込む前に人が見て決められるよう出す。
    name_owner = {}
    for s in staff_list:
        name_owner.setdefault(s["name_jp"], []).append(s["no"])
    for nm, nos in name_owner.items():
        if len(nos) > 1:
            warnings.append(
                f"「{nm}」が{len(nos)}人います（NO.{'・'.join(str(n) for n in nos)}）。"
                f"別人ならこのままで正しく、同じ人ならシフト表側でNO.を揃えてください"
            )

    if no_missing:
        warnings.append(
            f"NO.が空欄の人が{len(no_missing)}名います（{'、'.join(no_missing[:5])}"
            f"{' ほか' if len(no_missing) > 5 else ''}）。NO.なしは同一人物の判定ができません"
        )
    if not date_cols:
        warnings.append(
            "日付の列が1つも見つかりませんでした。見出し行の指定を確認してください"
        )

    return {
        "staff": staff_list,
        "dates": dates,
        "shifts": shift_list,
        "skipped": skipped,
        "warnings": warnings,
        "paren_cells": paren_cells,
        "excluded": excluded,
        "columns": columns,
        "header_row": hr,
        "mapping": m,
    }
