"""P1 Staff Manager — イベントテンプレート（JSON）

イベント1つ分の設定（基本情報・日別レート・地域別交通費）を JSON で授受するための
ロード／検証／DB投入／エクスポート機能を提供する。

【テンプレートスキーマ】
{
  "name": "P1 Kyoto 2026 夏大会",
  "venue": "京都劇場",
  "venue_prefecture": "京都府",
  "start_date": "2026-08-13",
  "end_date": "2026-08-17",
  "break_minutes_6h": 45,
  "break_minutes_8h": 60,
  "rate_template_id": "p1_standard",
  "dates": ["2026-08-13", "2026-08-14", ...],
  "rates": {
    "2026-08-13": {"hourly": 1500, "night": 1875, "transport": 1000,
                    "floor_bonus": 3000, "mix_bonus": 1500, "date_label": "regular"}, ...
  },
  "transport_rules": [
    {"region": "近畿", "max_amount": 1000, "receipt_required": 0,
     "is_venue_region": 1, "note": "開催地・一律支給"}, ...
  ]
}

【利用シーン】
- 中野さん: docs/event_templates/p1_blank.json をコピー → 編集 → アップロードで丸ごと投入
- 伊藤さん: GUI で微調整 → 完成版を JSON にエクスポートして次回大会のテンプレに流用
- CLI: scripts/seed_event.py path/to/event.json で一括投入

【後方互換】
- prefecture / rate_template_id カラム未マイグレ環境でも動作（utils/db_schema 経由）
- 既存の seed_nagoya.py は従来どおり利用可能
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


# ============================================================
# レートプリセット（コード組込み）
# ============================================================
# 同等の JSON が docs/event_templates/_presets/ にもある。
# UI から「プリセット適用」した時に即座に参照するためコードにも保持。

RATE_PRESETS: dict = {
    "p1_standard": {
        "label": "P1 標準",
        "description": "P1 Nagoya 2026 で実績のあるベース料金",
        "regular": {
            "hourly": 1500, "night": 1875, "transport": 1000,
            "floor_bonus": 3000, "mix_bonus": 1500,
        },
        "premium": {
            "hourly": 1600, "night": 2000, "transport": 1000,
            "floor_bonus": 5000, "mix_bonus": 1500,
        },
    },
    "usop_standard": {
        "label": "USOP 標準",
        "description": "USOP 2026/2-3月大会の参考レート（時給は P1 より低め）",
        "regular": {
            "hourly": 1400, "night": 1700, "transport": 1000,
            "floor_bonus": 3000, "mix_bonus": 3000,
        },
        "premium": {
            "hourly": 1500, "night": 1850, "transport": 1000,
            "floor_bonus": 5000, "mix_bonus": 3000,
        },
    },
    "minimum_aichi": {
        "label": "最低賃金（愛知）",
        "description": "愛知県最低賃金 ¥1,055 ベース。法定下限の参考値",
        "regular": {
            "hourly": 1055, "night": 1319, "transport": 1000,
            "floor_bonus": 3000, "mix_bonus": 1500,
        },
        "premium": {
            "hourly": 1055, "night": 1319, "transport": 1000,
            "floor_bonus": 5000, "mix_bonus": 1500,
        },
    },
}


# ============================================================
# 地域定義（参考値）
# ============================================================
# utils.region と整合する地域名を採用。
JAPAN_REGIONS: list = [
    "北海道", "東北", "関東", "甲信越", "北陸",
    "東海", "近畿", "中国", "四国", "九州", "沖縄",
]


# ============================================================
# 期間ユーティリティ
# ============================================================

def daterange(start: str, end: str) -> list:
    """YYYY-MM-DD の連続日付リストを返す（両端含む）"""
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    if e < s:
        raise ValueError(f"end_date {end} < start_date {start}")
    days = []
    cur = s
    while cur <= e:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return days


def build_rates_from_preset(preset_id: str, dates: list,
                             premium_dates: Optional[list] = None) -> dict:
    """プリセットから日別レート辞書を組み立てる

    Args:
        preset_id: RATE_PRESETS のキー
        dates: 対象日リスト（YYYY-MM-DD）
        premium_dates: その中で「premium」として扱う日リスト

    Returns:
        {"2025-12-29": {hourly, night, transport, floor_bonus, mix_bonus, date_label}, ...}
    """
    if preset_id not in RATE_PRESETS:
        raise ValueError(f"unknown preset: {preset_id}")
    preset = RATE_PRESETS[preset_id]
    premium_set = set(premium_dates or [])
    rates = {}
    for d in dates:
        kind = "premium" if d in premium_set else "regular"
        base = preset[kind].copy()
        base["date_label"] = kind
        rates[d] = base
    return rates


# ============================================================
# テンプレート I/O
# ============================================================

def load_template(path) -> dict:
    """JSON ファイルからテンプレを読み込む。pathlib / str / file-like を許容"""
    if hasattr(path, "read"):
        # file-like
        text = path.read()
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        return json.loads(text)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_template(tmpl: dict) -> list:
    """テンプレを検証。エラー文字列のリストを返す（空ならOK）"""
    errs: list = []
    required = ["name", "venue", "start_date", "end_date"]
    for k in required:
        if not tmpl.get(k):
            errs.append(f"必須フィールド '{k}' が空です")
    # 日付フォーマット
    for k in ("start_date", "end_date"):
        v = tmpl.get(k)
        if v:
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                errs.append(f"{k} は YYYY-MM-DD 形式にしてください: '{v}'")
    if errs:
        return errs
    # 期間整合性
    try:
        expected_dates = daterange(tmpl["start_date"], tmpl["end_date"])
    except ValueError as e:
        return [str(e)]
    # rates が指定されていれば日付整合をチェック
    rates = tmpl.get("rates") or {}
    if rates:
        for d in rates.keys():
            if d not in expected_dates:
                errs.append(f"rates に期間外の日付があります: {d}")
        # date_label の許容値
        for d, r in rates.items():
            label = r.get("date_label", "regular")
            if label not in ("regular", "premium"):
                errs.append(f"{d}: date_label は 'regular' / 'premium' のみ許容（'{label}'）")
    # transport_rules の整合
    rules = tmpl.get("transport_rules") or []
    seen_regions = set()
    for i, rule in enumerate(rules, 1):
        region = rule.get("region")
        if not region:
            errs.append(f"transport_rules[{i}]: region 必須")
        elif region in seen_regions:
            errs.append(f"transport_rules[{i}]: region '{region}' が重複")
        else:
            seen_regions.add(region)
        if "max_amount" in rule:
            try:
                int(rule["max_amount"])
            except (ValueError, TypeError):
                errs.append(f"transport_rules[{i}] '{region}': max_amount は整数")
    return errs


def apply_template(tmpl: dict, *, mode: str = "create",
                   event_id: Optional[int] = None) -> int:
    """テンプレを DB に投入

    Args:
        tmpl: load_template で読んだ辞書
        mode: "create" 新規作成 / "update" 既存更新（要 event_id）
        event_id: update 時に対象イベントID

    Returns:
        投入後の event_id
    """
    import db  # 遅延 import で循環回避
    errs = validate_template(tmpl)
    if errs:
        raise ValueError("テンプレ検証エラー:\n - " + "\n - ".join(errs))

    name = tmpl["name"]
    venue = tmpl["venue"]
    prefecture = tmpl.get("venue_prefecture") or tmpl.get("prefecture")
    start_date = tmpl["start_date"]
    end_date = tmpl["end_date"]
    break_6h = int(tmpl.get("break_minutes_6h", 45))
    break_8h = int(tmpl.get("break_minutes_8h", 60))
    rate_template_id = tmpl.get("rate_template_id", "")

    # 1. event 本体
    if mode == "create":
        eid = db.create_event(
            name=name, venue=venue,
            start_date=start_date, end_date=end_date,
            break_minutes_6h=break_6h, break_minutes_8h=break_8h,
            prefecture=prefecture, rate_template_id=rate_template_id,
        )
    elif mode == "update":
        if not event_id:
            raise ValueError("mode=update には event_id が必要")
        db.update_event_meta(
            event_id,
            name=name, venue=venue,
            start_date=start_date, end_date=end_date,
            break_minutes_6h=break_6h, break_minutes_8h=break_8h,
            prefecture=prefecture, rate_template_id=rate_template_id,
        )
        eid = event_id
    else:
        raise ValueError(f"unknown mode: {mode}")

    if not eid:
        raise RuntimeError("イベント作成に失敗しました")

    # 2. 日別レート
    rates = tmpl.get("rates") or {}
    if rates:
        rates_list = []
        for d, r in rates.items():
            rates_list.append({
                "date": d,
                "hourly": r.get("hourly", 1500),
                "night": r.get("night", 1875),
                "transport": r.get("transport", 1000),
                "floor_bonus": r.get("floor_bonus", 3000),
                "mix_bonus": r.get("mix_bonus", 1500),
                "date_label": r.get("date_label", "regular"),
            })
        db.bulk_set_event_rates(eid, rates_list)

    # 3. 地域別交通費ルール
    rules = tmpl.get("transport_rules") or []
    if rules:
        db.save_transport_rules(eid, rules)

    return eid


def export_event_to_template(event_id: int) -> dict:
    """既存イベントをテンプレ JSON 辞書としてエクスポート

    GUI 上で完成させたイベントを次回のテンプレに流用するためのもの。
    """
    import db
    ev = db.get_event_by_id(event_id)
    if not ev:
        raise ValueError(f"event_id={event_id} not found")
    rates_rows = db.get_event_rates(event_id)
    rules = db.get_transport_rules(event_id) or []
    rates = {}
    for r in rates_rows:
        rates[r["date"]] = {
            "hourly": r.get("hourly_rate", 1500),
            "night": r.get("night_rate", 1875),
            "transport": r.get("transport_allowance", 1000),
            "floor_bonus": r.get("floor_bonus", 3000),
            "mix_bonus": r.get("mix_bonus", 1500),
            "date_label": r.get("date_label", "regular"),
        }
    rule_list = []
    for r in rules:
        rule_list.append({
            "region": r.get("region"),
            "max_amount": int(r.get("max_amount", 0)),
            "receipt_required": int(r.get("receipt_required", 0)),
            "is_venue_region": int(r.get("is_venue_region", 0)),
            "note": r.get("note", "") or "",
        })
    out = {
        "name": ev.get("name"),
        "venue": ev.get("venue"),
        "venue_prefecture": ev.get("prefecture") or "",
        "start_date": ev.get("start_date"),
        "end_date": ev.get("end_date"),
        "break_minutes_6h": int(ev.get("break_minutes_6h") or 45),
        "break_minutes_8h": int(ev.get("break_minutes_8h") or 60),
        "rate_template_id": ev.get("rate_template_id") or "",
        "dates": daterange(ev["start_date"], ev["end_date"]),
        "rates": rates,
        "transport_rules": rule_list,
    }
    return out


def dump_template(tmpl: dict, *, indent: int = 2) -> str:
    """テンプレ辞書を JSON 文字列に。日本語はそのまま"""
    return json.dumps(tmpl, ensure_ascii=False, indent=indent)
