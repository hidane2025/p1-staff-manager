"""交通費ルール・領収書請求（db.py から2026-08-06に機械分割・挙動不変）"""
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


# === Transport Rules ===

def get_transport_rules(event_id):
    """イベントの地域別交通費ルールを取得"""
    return core.get_client().table("p1_event_transport_rules").select("*").eq(
        "event_id", event_id).order("region").execute().data


def save_transport_rules(event_id: int, rules: list[dict]):
    """交通費ルールを一括保存（既存削除→再挿入）

    rules: [{"region": "東海", "max_amount": 10000,
            "receipt_required": 1, "is_venue_region": 0, "note": ""}]
    """
    client = core.get_client()
    client.table("p1_event_transport_rules").delete().eq("event_id", event_id).execute()
    if not rules:
        return
    payload = []
    for r in rules:
        payload.append({
            "event_id": event_id,
            "region": r.get("region"),
            "max_amount": int(r.get("max_amount") or 0),
            "receipt_required": int(r.get("receipt_required") or 0),
            "is_venue_region": int(r.get("is_venue_region") or 0),
            "note": r.get("note", "") or "",
        })
    client.table("p1_event_transport_rules").insert(payload).execute()


# === Transport Claims ===

def get_transport_claims(event_id):
    """イベントの領収書金額一覧を取得"""
    return core.get_client().table("p1_transport_claims").select("*").eq(
        "event_id", event_id).execute().data


def upsert_transport_claim(event_id: int, staff_id: int,
                            receipt_amount: int, approved_amount: int,
                            has_receipt: int = 1, note: str = ""):
    """領収書金額を登録/更新"""
    client = core.get_client()
    existing = client.table("p1_transport_claims").select("id").eq(
        "event_id", event_id).eq("staff_id", staff_id).execute().data
    payload = {
        "event_id": event_id, "staff_id": staff_id,
        "receipt_amount": receipt_amount, "approved_amount": approved_amount,
        "has_receipt": has_receipt, "note": note,
        "updated_at": core._now(),
    }
    if existing:
        client.table("p1_transport_claims").update(payload).eq(
            "id", existing[0]["id"]).execute()
    else:
        client.table("p1_transport_claims").insert(payload).execute()


def get_staff_region(staff_id: int):
    """スタッフの地域を取得（address→region優先、未設定時はcontractorデフォルト）"""
    row = core.get_client().table("p1_staff").select(
        "region, prefecture, address").eq("id", staff_id).execute().data
    if not row:
        return None, None
    return row[0].get("region"), row[0].get("prefecture")
