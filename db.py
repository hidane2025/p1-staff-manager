"""P1 Staff Manager — データベース層 v3 (Supabase REST API)"""

import os
import streamlit as st
from datetime import datetime
from typing import Optional

try:
    from supabase import create_client
except ImportError:
    create_client = None

# Supabase接続情報（st.secretsまたは環境変数から取得）
def _get_supabase_config():
    """Supabase URL/Keyを取得"""
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except Exception:
        url = os.environ.get("SUPABASE_URL", "https://fmqalkwkxckbxxijiprp.supabase.co")
        key = os.environ.get("SUPABASE_KEY",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZtcWFsa3dreGNrYnh4aWppcHJwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU5ODU5NjgsImV4cCI6MjA5MTU2MTk2OH0.ECV0yK5b3H2GOZp--Q2iPvh8CmCrMO1h0fMadmm0fLo")
    return url, key


@st.cache_resource
def get_client():
    """Supabaseクライアントを取得（キャッシュ）"""
    url, key = _get_supabase_config()
    return create_client(url, key)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# === Audit Log ===

def log_action(action, target_type, target_id=None, detail="", event_id=None, performed_by="system"):
    """監査ログを記録"""
    try:
        get_client().table("p1_audit_log").insert({
            "event_id": event_id, "action": action, "target_type": target_type,
            "target_id": target_id, "detail": detail, "performed_by": performed_by
        }).execute()
    except Exception:
        pass  # ログ記録失敗はサイレント


def get_audit_log(event_id=None, limit=50):
    q = get_client().table("p1_audit_log").select("*").order("created_at", desc=True).limit(limit)
    if event_id:
        q = q.eq("event_id", event_id)
    return q.execute().data


# === Staff CRUD ===

def create_staff(no, name_jp, name_en="", role="Dealer", contact="", notes="",
                 real_name="", address="", email="",
                 employment_type="contractor", custom_hourly_rate=None):
    # 重複チェック: NO.が指定されていて既存の場合はエラーを投げる
    if no and no > 0:
        existing = get_client().table("p1_staff").select("id, name_jp").eq("no", no).execute()
        if existing.data:
            raise ValueError(f"NO.{no} は既に {existing.data[0]['name_jp']} で登録されています")
    r = get_client().table("p1_staff").insert({
        "no": no, "name_jp": name_jp, "name_en": name_en,
        "role": role, "contact": contact, "notes": notes,
        "real_name": real_name, "address": address, "email": email,
        "employment_type": employment_type,
        "custom_hourly_rate": custom_hourly_rate,
    }).execute()
    return r.data[0]["id"] if r.data else None


def get_all_staff(role_filter=None, search=None):
    q = get_client().table("p1_staff").select("*").eq("is_active", 1).order("role").order("no")
    if role_filter:
        q = q.eq("role", role_filter)
    data = q.execute().data
    if search:
        s = search.lower()
        data = [d for d in data if s in (d.get("name_jp") or "").lower()
                or s in (d.get("name_en") or "").lower()
                or s in str(d.get("no", ""))]
    return data


def get_staff_by_id(staff_id):
    r = get_client().table("p1_staff").select("*").eq("id", staff_id).execute()
    return r.data[0] if r.data else None


def update_staff(staff_id, **kwargs):
    kwargs["updated_at"] = _now()
    get_client().table("p1_staff").update(kwargs).eq("id", staff_id).execute()


def find_or_create_staff(no, name_jp, name_en="", role="Dealer"):
    r = get_client().table("p1_staff").select("id").eq("no", no).eq("name_jp", name_jp).execute()
    if r.data:
        return r.data[0]["id"]
    return create_staff(no, name_jp, name_en, role)


# === Event CRUD ===

def create_event(name, venue, start_date, end_date, break_minutes_6h=45, break_minutes_8h=60):
    r = get_client().table("p1_events").insert({
        "name": name, "venue": venue, "start_date": start_date, "end_date": end_date,
        "break_minutes_6h": break_minutes_6h, "break_minutes_8h": break_minutes_8h
    }).execute()
    return r.data[0]["id"] if r.data else None


def get_all_events():
    return get_client().table("p1_events").select("*").order("start_date", desc=True).execute().data


def get_event_by_id(event_id):
    r = get_client().table("p1_events").select("*").eq("id", event_id).execute()
    return r.data[0] if r.data else None


# === Event Rates ===

def set_event_rate(event_id, date, hourly_rate=1500, night_rate=1875,
                   transport=1000, floor_bonus=3000, mix_bonus=1500, date_label="regular"):
    client = get_client()
    client.table("p1_event_rates").delete().eq("event_id", event_id).eq("date", date).execute()
    client.table("p1_event_rates").insert({
        "event_id": event_id, "date": date, "date_label": date_label,
        "hourly_rate": hourly_rate, "night_rate": night_rate,
        "transport_allowance": transport, "floor_bonus": floor_bonus, "mix_bonus": mix_bonus
    }).execute()


def get_event_rates(event_id):
    return get_client().table("p1_event_rates").select("*").eq("event_id", event_id).order("date").execute().data


# === Shifts ===

def upsert_shift(event_id, staff_id, date, planned_start, planned_end, is_mix=0):
    client = get_client()
    existing = client.table("p1_shifts").select("id").eq("event_id", event_id).eq("staff_id", staff_id).eq("date", date).execute()
    if existing.data:
        client.table("p1_shifts").update({
            "planned_start": planned_start, "planned_end": planned_end, "is_mix": is_mix
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        client.table("p1_shifts").insert({
            "event_id": event_id, "staff_id": staff_id, "date": date,
            "planned_start": planned_start, "planned_end": planned_end, "is_mix": is_mix
        }).execute()


def _flatten_staff_join(data):
    """Supabase結合結果のp1_staffが dict/list いずれでもフラット化"""
    for row in data:
        staff_info = row.pop("p1_staff", None)
        if isinstance(staff_info, list):
            staff_info = staff_info[0] if staff_info else {}
        if not isinstance(staff_info, dict):
            staff_info = {}
        row["name_jp"] = staff_info.get("name_jp", "")
        row["name_en"] = staff_info.get("name_en", "")
        row["no"] = staff_info.get("no", 0)
        row["role"] = staff_info.get("role", "Dealer")
    return data


def get_shifts_for_event(event_id, date=None, staff_id=None):
    client = get_client()
    q = client.table("p1_shifts").select("*, p1_staff(name_jp, name_en, no, role)").eq("event_id", event_id)
    if date:
        q = q.eq("date", date)
    if staff_id:
        q = q.eq("staff_id", staff_id)
    data = q.order("staff_id").execute().data
    return _flatten_staff_join(data)


def checkin_staff(shift_id, actual_start):
    client = get_client()
    row = client.table("p1_shifts").select("status, actual_end").eq("id", shift_id).execute().data
    if row and row[0].get("actual_end"):
        client.table("p1_shifts").update({"actual_start": actual_start}).eq("id", shift_id).execute()
    else:
        client.table("p1_shifts").update({
            "actual_start": actual_start, "status": "checked_in"
        }).eq("id", shift_id).execute()


def checkout_staff(shift_id, actual_end):
    get_client().table("p1_shifts").update({
        "actual_end": actual_end, "status": "checked_out"
    }).eq("id", shift_id).execute()


def bulk_checkout(shift_ids, actual_end, event_id=None):
    client = get_client()
    for sid in shift_ids:
        row = client.table("p1_shifts").select("planned_start, actual_start").eq("id", sid).execute().data
        a_start = (row[0].get("actual_start") or row[0].get("planned_start")) if row else None
        client.table("p1_shifts").update({
            "actual_end": actual_end, "actual_start": a_start, "status": "checked_out"
        }).eq("id", sid).execute()
    if event_id:
        log_action("bulk_checkout", "shifts", detail=f"{len(shift_ids)}名を{actual_end}で一括退勤", event_id=event_id)


def mark_absent(shift_id):
    get_client().table("p1_shifts").update({
        "status": "absent", "actual_start": None, "actual_end": None
    }).eq("id", shift_id).execute()


def set_shift_mix(shift_id, is_mix):
    get_client().table("p1_shifts").update({"is_mix": is_mix}).eq("id", shift_id).execute()


# === Payments ===

def save_payment(event_id, staff_id, base_pay, night_pay, transport_total,
                 floor_bonus_total, mix_bonus_total, attendance_bonus,
                 total_amount, break_deduction=0, adjustment=0, adjustment_note=""):
    client = get_client()
    existing = client.table("p1_payments").select("id, status").eq("event_id", event_id).eq("staff_id", staff_id).execute()
    if existing.data and existing.data[0]["status"] == "paid":
        return  # 支払済みは上書きしない
    if existing.data:
        client.table("p1_payments").delete().eq("id", existing.data[0]["id"]).execute()
    client.table("p1_payments").insert({
        "event_id": event_id, "staff_id": staff_id,
        "base_pay": base_pay, "night_pay": night_pay, "transport_total": transport_total,
        "floor_bonus_total": floor_bonus_total, "mix_bonus_total": mix_bonus_total,
        "attendance_bonus": attendance_bonus, "break_deduction": break_deduction,
        "adjustment": adjustment, "adjustment_note": adjustment_note, "total_amount": total_amount
    }).execute()
    log_action("calculate_payment", "payments", staff_id, f"合計¥{total_amount:,}", event_id)


def get_payments_for_event(event_id):
    data = get_client().table("p1_payments").select("*, p1_staff(name_jp, name_en, no, role)").eq("event_id", event_id).order("staff_id").execute().data
    return _flatten_staff_join(data)


def get_yearly_totals(year, staff_id=None):
    """指定年(1/1〜12/31)の全スタッフ累計支払額を取得

    Returns: [{staff_id, name_jp, no, role, employment_type,
              total_amount, event_count, event_names}]
    """
    client = get_client()
    # その年のイベント一覧
    events = client.table("p1_events").select("id, name").gte(
        "start_date", f"{year}-01-01").lte("start_date", f"{year}-12-31").execute().data
    event_ids = [e["id"] for e in events]
    event_name_map = {e["id"]: e["name"] for e in events}
    if not event_ids:
        return []

    # 支払いを取得
    q = client.table("p1_payments").select("*").in_("event_id", event_ids)
    if staff_id:
        q = q.eq("staff_id", staff_id)
    payments = q.execute().data

    # スタッフ情報を別途取得（結合のdict/list不確定問題を回避）
    staff_ids = list({p["staff_id"] for p in payments})
    if not staff_ids:
        return []
    staff_data = client.table("p1_staff").select(
        "id, name_jp, name_en, no, role, employment_type, real_name, email, address"
    ).in_("id", staff_ids).execute().data
    staff_map = {s["id"]: s for s in staff_data}

    # スタッフごとに集計
    totals = {}
    for p in payments:
        s_id = p["staff_id"]
        staff_info = staff_map.get(s_id, {})
        if s_id not in totals:
            totals[s_id] = {
                "staff_id": s_id,
                "name_jp": staff_info.get("name_jp", ""),
                "name_en": staff_info.get("name_en", ""),
                "no": staff_info.get("no", 0),
                "role": staff_info.get("role", "Dealer"),
                "employment_type": staff_info.get("employment_type", "contractor"),
                "real_name": staff_info.get("real_name") or "",
                "email": staff_info.get("email") or "",
                "address": staff_info.get("address") or "",
                "total_amount": 0,
                "paid_amount": 0,
                "event_count": 0,
                "event_names": set(),
            }
        totals[s_id]["total_amount"] += p.get("total_amount", 0)
        if p.get("status") == "paid":
            totals[s_id]["paid_amount"] += p.get("total_amount", 0)
        totals[s_id]["event_count"] += 1
        totals[s_id]["event_names"].add(event_name_map.get(p["event_id"], ""))

    # setをlistに変換
    result = []
    for v in totals.values():
        v["event_names"] = sorted(v["event_names"])
        result.append(v)
    return sorted(result, key=lambda x: -x["total_amount"])


def approve_payment(payment_id, approved_by, event_id=None):
    get_client().table("p1_payments").update({
        "status": "approved", "approved_by": approved_by, "approved_at": _now()
    }).eq("id", payment_id).execute()
    log_action("approve_payment", "payments", payment_id, f"承認者: {approved_by}", event_id)


def mark_paid(payment_id, event_id=None):
    get_client().table("p1_payments").update({
        "status": "paid", "paid_at": _now()
    }).eq("id", payment_id).execute()
    log_action("mark_paid", "payments", payment_id, "", event_id)


def mark_receipt_received(payment_id, event_id=None):
    get_client().table("p1_payments").update({"receipt_received": 1}).eq("id", payment_id).execute()
    log_action("receipt_received", "payments", payment_id, "", event_id)


# === Petty Cash ===

def add_petty_cash(event_id, date, description, amount, requester, approver=""):
    get_client().table("p1_petty_cash").insert({
        "event_id": event_id, "date": date, "description": description,
        "amount": amount, "requester": requester, "approver": approver
    }).execute()
    log_action("add_petty_cash", "petty_cash", detail=f"¥{amount:,} {description}", event_id=event_id)


def get_petty_cash_for_event(event_id):
    return get_client().table("p1_petty_cash").select("*").eq("event_id", event_id).order("date").order("created_at").execute().data


# === 互換性のためのinit_db（何もしない） ===
def init_db():
    pass
