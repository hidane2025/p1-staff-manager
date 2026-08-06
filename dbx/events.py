"""イベントと日別単価（db.py から2026-08-06に機械分割・挙動不変）"""
import os
import re
import unicodedata
import streamlit as st
from datetime import datetime, timezone, timedelta
from typing import Optional
try:
    from supabase import create_client
except ImportError:
    create_client = None

from dbx import core


# === Event CRUD ===

def create_event(name, venue, start_date, end_date, break_minutes_6h=0, break_minutes_8h=0,
                 prefecture=None, rate_template_id=""):
    """イベントを新規作成

    Args:
        name: イベント名
        venue: 会場名
        start_date / end_date: YYYY-MM-DD
        break_minutes_6h: 6時間超勤務時の休憩控除（分）。デフォルト 0 = 控除なし
            （Pacific 運用方針: 過去から休憩控除は実施していない）
        break_minutes_8h: 8時間超勤務時の休憩控除（分）。デフォルト 0 = 控除なし
        prefecture: 開催地都道府県（地域別交通費の起点）。マイグレ未実行時は無視
        rate_template_id: レートプリセット識別子（例 "p1_standard"）。マイグレ未実行時は無視

    Returns:
        作成された event_id（失敗時 None）
    """
    from utils import db_schema
    payload = {
        "name": name, "venue": venue, "start_date": start_date, "end_date": end_date,
        "break_minutes_6h": break_minutes_6h, "break_minutes_8h": break_minutes_8h,
        # 2026-08-06: DB列の既定値が旧社名「株式会社パシフィック」のままのため、
        # ここで現行の発行者名義を明示し、DB既定値に落とさない。放置すると
        # 新規大会の契約書・領収書の甲が旧社名で発行される（運営会社は
        # PRT→株式会社P1 Entertainment へ移行済み・商号変更日2026-06-30、
        # 2026-07-25 領収書名義移行）。住所は登記上の本店所在地
        # （法人番号1180001113559・中野さん提供 2026-08-06）。
        # DB側の既定値修正は docs/db_migrations/20260806_fix_issuer_default.sql
        # （SQL実行権限の回復待ち）。既存イベントの名義はここでは変更しない。
        "issuer_name": "株式会社P1 Entertainment",
        "issuer_address": "愛知県名古屋市東区泉1丁目23番37号",
    }
    # マイグレ後のカラムは存在チェックして条件付きで投入
    if prefecture and db_schema.has_column("p1_events", "prefecture"):
        payload["prefecture"] = prefecture
    if rate_template_id and db_schema.has_column("p1_events", "rate_template_id"):
        payload["rate_template_id"] = rate_template_id
    r = core.get_client().table("p1_events").insert(payload).execute()
    return r.data[0]["id"] if r.data else None


def update_event_meta(event_id: int, **kwargs) -> None:
    """イベントのメタ情報を更新

    Args:
        event_id: 対象イベントID
        **kwargs: name / venue / prefecture / start_date / end_date /
                  break_minutes_6h / break_minutes_8h / rate_template_id /
                  show_tax_breakdown のいずれか

    マイグレ未実行のカラムは自動でドロップして更新する（後方互換）。
    """
    from utils import db_schema
    if not kwargs:
        return
    # 後方互換が必要なカラム
    optional_columns = {
        "prefecture": "prefecture",
        "rate_template_id": "rate_template_id",
        "show_tax_breakdown": "show_tax_breakdown",
        "rounding_unit": "rounding_unit",  # A-6 (2026-06-01): 端数処理単位
    }
    payload = {}
    for k, v in kwargs.items():
        if k in optional_columns:
            if db_schema.has_column("p1_events", optional_columns[k]):
                payload[k] = v
            # マイグレ未実行ならスキップ
        else:
            payload[k] = v
    if not payload:
        return
    core.get_client().table("p1_events").update(payload).eq("id", event_id).execute()


def get_all_events():
    return core.get_client().table("p1_events").select("*").order("start_date", desc=True).execute().data


def get_event_by_id(event_id):
    r = core.get_client().table("p1_events").select("*").eq("id", event_id).execute()
    return r.data[0] if r.data else None


# === Event Rates ===

def set_event_rate(event_id, date, hourly_rate=1500, night_rate=1875,
                   transport=1000, floor_bonus=3000, mix_bonus=1500, date_label="regular"):
    client = core.get_client()
    # 2026-07-29 修正: 削除→挿入だと挿入失敗時に単価設定が消える。更新 or 挿入に変更。
    _payload = {
        "event_id": event_id, "date": date, "date_label": date_label,
        "hourly_rate": hourly_rate, "night_rate": night_rate,
        "transport_allowance": transport, "floor_bonus": floor_bonus, "mix_bonus": mix_bonus,
    }
    _existing = client.table("p1_event_rates").select("id").eq(
        "event_id", event_id).eq("date", date).execute().data
    if _existing:
        client.table("p1_event_rates").update(_payload).eq("id", _existing[0]["id"]).execute()
    else:
        client.table("p1_event_rates").insert(_payload).execute()


def get_event_rates(event_id):
    return core.get_client().table("p1_event_rates").select("*").eq("event_id", event_id).order("date").execute().data


def bulk_set_event_rates(event_id: int, rates: list) -> int:
    """イベントの日別レートを一括設定

    Args:
        event_id: 対象イベントID
        rates: [{"date": "2025-12-29", "hourly": 1500, "night": 1875,
                 "transport": 1000, "floor_bonus": 3000, "mix_bonus": 1500,
                 "date_label": "regular"}, ...]

    既存レートは削除して全置換する（イベント単位の冪等操作）。
    Returns: 投入件数
    """
    client = core.get_client()
    if not rates:
        return 0
    # 一旦全削除（同じevent_idのレコード）
    client.table("p1_event_rates").delete().eq("event_id", event_id).execute()
    payload = []
    for r in rates:
        payload.append({
            "event_id": event_id,
            "date": r.get("date"),
            "date_label": r.get("date_label", "regular"),
            "hourly_rate": int(r.get("hourly") or r.get("hourly_rate") or 1500),
            "night_rate": int(r.get("night") or r.get("night_rate") or 1875),
            "transport_allowance": int(r.get("transport") or r.get("transport_allowance") or 1000),
            "floor_bonus": int(r.get("floor_bonus") or 3000),
            "mix_bonus": int(r.get("mix_bonus") or 1500),
        })
    client.table("p1_event_rates").insert(payload).execute()
    core.log_action("bulk_set_rates", "event_rates", event_id,
               detail=f"{len(payload)}日分のレートを一括設定", event_id=event_id)
    return len(payload)
