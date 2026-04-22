"""P1 Staff Manager — Google フォーム CSV インポーター

Google フォームの既定 CSV 出力（タイムスタンプ列 + 各設問を列名とする書式）を読み込み、
`db.bulk_import_staff()` が受け付ける dict 形式に変換するユーティリティ。

対応する質問テンプレは `docs/gform_staff_onboarding_template.md` に収録。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

# ---------------------------------------------------------------------------
# マッピング定義
# ---------------------------------------------------------------------------

# P1 Staff Manager の内部カラム一覧（bulk_import_staff が解釈するキー）
_P1_COLUMNS: tuple[str, ...] = (
    "no",
    "name_jp",
    "name_en",
    "real_name",
    "address",
    "email",
    "nearest_station",
    "contact",
    "role",
    "employment_type",
    "custom_hourly_rate",
    "notes",
)

# Google フォームの質問文（完全一致・前方一致の順にマッチさせる）
# key: 正規化後の質問文キーワード（部分一致許可）
# value: ("target_column", "note_label")
#   - target_column: 直接入れるカラム名、または "_notes" を指定すると notes に統合
#   - note_label: notes 統合時に付ける接頭辞（空なら質問文を使わずそのまま追記）
_QUESTION_MAP: dict[str, tuple[str, str]] = {
    # 直接マッピング（そのまま該当カラムへ）
    "お名前（本名": ("real_name", ""),
    "本名": ("real_name", ""),
    "ディーラーネーム": ("name_jp", ""),
    "現場での呼び名": ("name_jp", ""),
    "メールアドレス": ("email", ""),
    "ご住所": ("address", ""),
    "住所": ("address", ""),
    "最寄駅": ("nearest_station", ""),
    "最寄り駅": ("nearest_station", ""),
    "電話番号": ("contact", ""),
    "役職": ("role", ""),
    "ポジション": ("role", ""),
    "雇用区分": ("employment_type", ""),
    "希望時給": ("custom_hourly_rate", ""),
    "タイミーの場合": ("custom_hourly_rate", ""),
    # notes に統合するもの
    "お名前（カタカナ": ("_notes", "フリガナ"),
    "フリガナ": ("_notes", "フリガナ"),
    "生年月日": ("_notes", "生年月日"),
    "性別": ("_notes", "性別"),
    "LINE": ("_notes", "LINE"),
    "緊急連絡先": ("_notes", "緊急連絡先"),
    "郵便番号": ("_address_prefix", "〒"),
    "MIX": ("_notes", "MIX対応"),
    "稼働可能曜日": ("_notes", "稼働可能曜日"),
    "開始希望日": ("_notes", "開始希望日"),
    "過去の大会運営経験": ("_notes", "過去の運営経験"),
    "その他": ("_notes", "その他"),
    "タイムスタンプ": ("_notes", "フォーム回答日時"),
}

_ROLE_MAP: dict[str, str] = {
    "ディーラー": "Dealer",
    "DEALER": "Dealer",
    "フロア": "Floor",
    "FLOOR": "Floor",
    "TD": "TD",
    "CHIP": "Chip",
    "チップ": "Chip",
    "DC": "DC",
}

_EMPLOYMENT_MAP: dict[str, str] = {
    "業務委託": "contractor",
    "タイミー": "timee",
    "正社員": "fulltime",
    "CONTRACTOR": "contractor",
    "TIMEE": "timee",
    "FULLTIME": "fulltime",
}


# ---------------------------------------------------------------------------
# 小さなヘルパー
# ---------------------------------------------------------------------------

def _normalize_header(col: str) -> str:
    """列名を正規化（前後空白除去・全角スペース変換）"""
    if col is None:
        return ""
    return str(col).replace("\u3000", " ").strip()


def _resolve_column(header: str) -> tuple[str, str] | None:
    """1つの列名から (target, note_label) を解決。未知なら None。"""
    h = _normalize_header(header)
    if not h:
        return None
    # 完全一致優先
    if h in _QUESTION_MAP:
        return _QUESTION_MAP[h]
    # 部分一致（質問文の先頭キーワードで照合）
    for key, value in _QUESTION_MAP.items():
        if key in h:
            return value
    return None


def _extract_digits(s: str) -> str:
    """文字列から数字だけを抜き出す"""
    return re.sub(r"\D", "", s or "")


def _normalize_role(raw: str) -> tuple[str, list[str]]:
    """役職文字列を (最初の役職, 残りの役職リスト) に分割。

    Google フォームのチェックボックスは "," または ";" 区切りで複数値を返す。
    """
    if not raw:
        return "", []
    parts = re.split(r"[,;、／/]", raw)
    cleaned: list[str] = []
    for part in parts:
        t = part.strip()
        if not t:
            continue
        mapped = _ROLE_MAP.get(t, _ROLE_MAP.get(t.upper(), t))
        cleaned.append(mapped)
    if not cleaned:
        return "", []
    return cleaned[0], cleaned[1:]


def _normalize_employment(raw: str) -> str:
    """雇用区分を内部コードに変換。未知の値は空文字を返す（フォールバックはDB層）。"""
    if not raw:
        return ""
    t = raw.strip()
    if t in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[t]
    return _EMPLOYMENT_MAP.get(t.upper(), "")


def _append_note(notes: list[str], label: str, value: str) -> None:
    """notes リストにラベル付きで追記（空値はスキップ）"""
    v = (value or "").strip()
    if not v:
        return
    if label:
        notes.append(f"{label}: {v}")
    else:
        notes.append(v)


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ParsedRow:
    """中間表現（パース結果の内部ホルダ）"""

    data: dict


def parse_gform_csv(file_content: bytes) -> list[dict]:
    """Google フォームの CSV を P1 Staff Manager 取込形式に変換する。

    Args:
        file_content: CSV ファイルのバイト列（UTF-8 BOM 付き可）

    Returns:
        bulk_import_staff() に渡せる dict のリスト。
        各 dict は `_P1_COLUMNS` のキーを持つ（値が無いキーは空文字）。
    """
    if file_content is None:
        return []
    if not isinstance(file_content, (bytes, bytearray)):
        raise TypeError("file_content must be bytes")
    if len(file_content) == 0:
        return []

    text = bytes(file_content).decode("utf-8-sig", errors="replace")
    # 空行や BOM だけの入力は空で返す
    if not text.strip():
        return []

    # 先頭行のセパレータ推定（Google Form は基本 "," だが TSV 保存されてたケースも考慮）
    first_line = text.split("\n", 1)[0]
    sep = "\t" if "\t" in first_line and first_line.count("\t") > first_line.count(",") else ","

    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str).fillna("")
    df.columns = [_normalize_header(c) for c in df.columns]

    rows: list[dict] = []
    for _, raw in df.iterrows():
        rows.append(_convert_row(raw.to_dict()))
    return rows


def _convert_row(raw: dict) -> dict:
    """1行分の dict を P1 形式に変換。"""
    out: dict = {col: "" for col in _P1_COLUMNS}
    notes: list[str] = []
    address_prefix = ""

    role_value_raw = ""

    for col, value in raw.items():
        resolved = _resolve_column(col)
        if resolved is None:
            # 未知列は丸ごと notes に吸収（情報ロスを防ぐ）
            _append_note(notes, _normalize_header(col), str(value or ""))
            continue
        target, label = resolved
        v = ("" if value is None else str(value)).strip()

        if target == "role":
            role_value_raw = v
            continue
        if target == "employment_type":
            code = _normalize_employment(v)
            if code:
                out["employment_type"] = code
            elif v:
                _append_note(notes, "雇用区分（不明）", v)
            continue
        if target == "custom_hourly_rate":
            digits = _extract_digits(v)
            if digits:
                out["custom_hourly_rate"] = digits
            continue
        if target == "_notes":
            _append_note(notes, label, v)
            continue
        if target == "_address_prefix":
            if v:
                # 〒マークは重複させない
                v_clean = v if v.startswith("〒") else f"{label}{v}" if label else v
                address_prefix = f"{v_clean} "
            continue
        # 直接マッピング列
        if target in out:
            # 既に値があれば上書きしない（先勝ち）。空なら書き込む。
            if not out[target]:
                out[target] = v

    # 役職（複数選択）を分解
    if role_value_raw:
        first, rest = _normalize_role(role_value_raw)
        if first:
            out["role"] = first
        if rest:
            _append_note(notes, "対応可能な追加役職", ", ".join(rest))

    # 住所の先頭に郵便番号を結合
    if address_prefix and out.get("address"):
        out["address"] = f"{address_prefix}{out['address']}".strip()
    elif address_prefix and not out.get("address"):
        # 郵便番号のみ → notes に入れて address は空のまま
        _append_note(notes, "郵便番号", address_prefix.strip())

    # ディーラーネーム空なら本名をフォールバック（bulk_import_staff の必須条件を満たすため）
    if not out["name_jp"] and out["real_name"]:
        out["name_jp"] = out["real_name"]

    # notes を結合
    if notes:
        out["notes"] = " / ".join(notes)

    return out


def validate_gform_row(row: dict) -> list[str]:
    """1行分のデータをバリデーションし、エラーメッセージのリストを返す。

    空リスト＝合格。フィールド欠損や形式不正を人間可読なメッセージで列挙する。
    """
    if not isinstance(row, dict):
        return ["行データが辞書ではありません"]

    errors: list[str] = []

    real_name = (row.get("real_name") or "").strip()
    if not real_name:
        errors.append("本名（real_name）が空です")

    email = (row.get("email") or "").strip()
    if not email:
        errors.append("メールアドレス（email）が空です")
    elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        errors.append(f"メールアドレスの形式が不正です: {email}")

    contact = (row.get("contact") or "").strip()
    # 電話番号が contact に入っているかチェック。LINE ID のみでも許容するが、
    # 数字を1つも含まない場合は警告（緊急連絡が取れなくなるため）
    if not contact:
        errors.append("電話番号（contact）が空です")
    else:
        has_phone_like = bool(re.search(r"\d{9,}", contact.replace("-", "").replace(" ", "")))
        if not has_phone_like:
            errors.append(f"電話番号の桁数が不足しています: {contact}")

    return errors


def validate_gform_rows(rows: Iterable[dict]) -> list[tuple[int, list[str]]]:
    """複数行を一括バリデーション。

    Returns:
        [(行番号（1始まり）, [エラーメッセージ, ...]), ...] エラーがある行のみ。
    """
    result: list[tuple[int, list[str]]] = []
    for i, row in enumerate(rows, 1):
        errors = validate_gform_row(row)
        if errors:
            result.append((i, errors))
    return result
