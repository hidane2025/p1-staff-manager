"""P1 Staff Manager — データベース層 v3 (Supabase REST API)"""

import os
import re
import unicodedata
import streamlit as st
from datetime import datetime, timezone, timedelta
from typing import Optional

# 日本時間（JST = UTC+9）で統一
_JST = timezone(timedelta(hours=9))

try:
    from supabase import create_client
except ImportError:
    create_client = None

# Supabase接続情報（st.secretsまたは環境変数から取得）
# 本番のキーは .streamlit/secrets.toml または環境変数に設定
# デフォルトはanon公開キー（RLS有効＋allow_allポリシー）だが、機密データを扱う場合は必ず上書きすること
_DEFAULT_SUPABASE_URL = "https://fmqalkwkxckbxxijiprp.supabase.co"
_DEFAULT_SUPABASE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZtcWFsa3dreGNrYnh4aWppcHJwIiwicm9sZSI6ImFub24i"
    "LCJpYXQiOjE3NzU5ODU5NjgsImV4cCI6MjA5MTU2MTk2OH0."
    "ECV0yK5b3H2GOZp--Q2iPvh8CmCrMO1h0fMadmm0fLo"
)


def _get_supabase_config():
    """Supabase URL/Keyを取得。

    Key優先度: SUPABASE_SERVICE_KEY > SUPABASE_KEY(anon) > 環境変数 > デフォルトanon。
    Streamlitはサーバ側で動くため service_role キーを使ってもブラウザに露出しない。
    SUPABASE_SERVICE_KEY を設定すればアプリ全体が service_role で動くので、PIIテーブルの
    anon権限を締めても壊れない（A-1是正の前提）。未設定時は従来どおり anon にフォールバック。
    """
    def _secret(name):
        try:
            return st.secrets.get(name)
        except Exception:
            return None

    url = _secret("SUPABASE_URL") or os.environ.get("SUPABASE_URL", _DEFAULT_SUPABASE_URL)
    key = (
        _secret("SUPABASE_SERVICE_KEY")
        or _secret("SUPABASE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY", _DEFAULT_SUPABASE_KEY)
    )
    return str(url), str(key)


@st.cache_resource
def get_client():
    """Supabaseクライアントを取得（キャッシュ）"""
    url, key = _get_supabase_config()
    return create_client(url, key)


def _now():
    """JSTの現在時刻を返す（Supabaseに保存する日時を統一）"""
    return datetime.now(_JST).strftime("%Y-%m-%d %H:%M:%S")


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
                 employment_type="contractor", custom_hourly_rate=None,
                 nearest_station="", prefecture=None, region=None):
    from utils.region import address_to_region
    # 重複チェック: NO.が指定されていて既存の場合はエラーを投げる
    if no and no > 0:
        existing = get_client().table("p1_staff").select("id, name_jp").eq("no", no).execute()
        if existing.data:
            raise ValueError(f"NO.{no} は既に {existing.data[0]['name_jp']} で登録されています")
    # 住所から都道府県・地域を自動判定（明示指定が無ければ）
    if address and (not prefecture or not region):
        auto_pref, auto_region = address_to_region(address)
        prefecture = prefecture or auto_pref
        region = region or auto_region
    r = get_client().table("p1_staff").insert({
        "no": no, "name_jp": name_jp, "name_en": name_en,
        "role": role, "contact": contact, "notes": notes,
        "real_name": real_name, "address": address, "email": email,
        "employment_type": employment_type,
        "custom_hourly_rate": custom_hourly_rate,
        "nearest_station": nearest_station,
        "prefecture": prefecture, "region": region,
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
    # 住所が変わったら都道府県・地域も再判定
    if "address" in kwargs and kwargs["address"]:
        from utils.region import address_to_region
        pref, region = address_to_region(kwargs["address"])
        if pref and "prefecture" not in kwargs:
            kwargs["prefecture"] = pref
        if region and "region" not in kwargs:
            kwargs["region"] = region
    kwargs["updated_at"] = _now()
    get_client().table("p1_staff").update(kwargs).eq("id", staff_id).execute()


# ============================================================
# スタッフ名寄せ（同一人物判定）— 源泉徴収/法定調書を人単位で正確にする土台
# ============================================================
def _norm_key(s) -> str:
    """名寄せ用の正規化キー。

    全角/半角・大文字小文字・空白の揺れを吸収する（NFKC正規化＋空白除去＋casefold）。
    例: "Eve Kat" / "ＥＶＥ　ＫＡＴ" / "evekat" → すべて "evekat"
    """
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", str(s))
    t = re.sub(r"\s+", "", t)
    return t.casefold()


def _build_staff_index(all_staff: list[dict]) -> dict:
    """既存スタッフから名寄せ用インデックスを構築。

    照合優先度: NO. > メール(正規化) > ディーラーネーム(正規化)。
    name_jp は別人が同名のこともあるため list で保持し、複数該当を検知できるようにする。
    """
    by_no: dict = {}
    by_email: dict = {}
    by_nname: dict = {}
    for s in all_staff:
        no = s.get("no")
        if no not in (None, ""):
            try:
                by_no.setdefault(int(no), s)
            except (ValueError, TypeError):
                pass
        ek = _norm_key(s.get("email"))
        if ek:
            by_email.setdefault(ek, s)
        nk = _norm_key(s.get("name_jp"))
        if nk:
            by_nname.setdefault(nk, []).append(s)
    return {"by_no": by_no, "by_email": by_email, "by_nname": by_nname}


def _match_staff(no, name_jp, email, index: dict):
    """インデックスから既存スタッフを探す（名寄せ）。

    Returns: (existing dict or None, matched_by)
      matched_by: "no" / "email" / "name_jp" / "name_jp_multi" / ""
      同名が複数該当する場合は "name_jp_multi"（呼び出し側で要確認警告を出せる）。
    """
    by_no = index["by_no"]
    if no not in (None, ""):
        try:
            ni = int(no)
        except (ValueError, TypeError):
            ni = None
        if ni is not None and ni in by_no:
            return by_no[ni], "no"
    ek = _norm_key(email)
    if ek and ek in index["by_email"]:
        return index["by_email"][ek], "email"
    nk = _norm_key(name_jp)
    if nk and nk in index["by_nname"]:
        cand = index["by_nname"][nk]
        return cand[0], ("name_jp_multi" if len(cand) > 1 else "name_jp")
    return None, ""


def _index_add(index: dict, staff: dict) -> None:
    """新規/更新したスタッフをインデックスに反映（同一バッチ内の二重取込を吸収）。"""
    no = staff.get("no")
    if no not in (None, ""):
        try:
            index["by_no"].setdefault(int(no), staff)
        except (ValueError, TypeError):
            pass
    ek = _norm_key(staff.get("email"))
    if ek:
        index["by_email"].setdefault(ek, staff)
    nk = _norm_key(staff.get("name_jp"))
    if nk:
        index["by_nname"].setdefault(nk, []).append(staff)


def bulk_import_staff(rows: list[dict]) -> dict:
    """スタッフ情報を一括登録/更新（名寄せ付き）

    同一人物判定（名寄せ）の優先度: NO. > メール(正規化) > ディーラーネーム(正規化)。
    全角/半角・大文字小文字・空白の揺れを吸収して二重登録を防ぎ、同一バッチ内の
    重複も吸収する。表記揺れでの統合・同名衝突は warnings に記録（自動統合の透明化）。

    Args:
        rows: [{"no": 18, "name_jp": "EveKat", "real_name": "...",
                "address": "...", "email": "...", "nearest_station": "...",
                "employment_type": "contractor", ...}]
    Returns:
        {"created": N, "updated": M, "errors": [str, ...], "warnings": [str, ...]}
    """
    from utils.region import address_to_region
    client = get_client()
    created = 0
    updated = 0
    errors = []
    warnings = []

    # 名寄せ用に既存スタッフを1回だけ取得してインデックス化（行ごとSELECTのN+1回避）
    try:
        existing_all = client.table("p1_staff").select("*").execute().data or []
    except Exception:
        existing_all = []
    index = _build_staff_index(existing_all)

    for i, row in enumerate(rows, 1):
        name_jp = (row.get("name_jp") or "").strip()
        if not name_jp:
            errors.append(f"行{i}: 名前が空")
            continue
        no = row.get("no")
        try:
            no = int(no) if no not in (None, "") else None
        except (ValueError, TypeError):
            no = None
        email_val = (row.get("email") or "").strip()

        # 名寄せ: NO. > メール(正規化) > ディーラーネーム(正規化)
        existing, matched_by = _match_staff(no, name_jp, email_val, index)

        # 自動統合の透明化（人が後で確認できるよう warnings に残す）
        if existing:
            exist_name = (existing.get("name_jp") or "").strip()
            if matched_by == "email" and _norm_key(exist_name) != _norm_key(name_jp):
                warnings.append(
                    f"行{i}: メール一致で「{exist_name}」(NO.{existing.get('no')}) に統合"
                    f"（入力名「{name_jp}」と相違・要確認）"
                )
            elif matched_by == "name_jp" and exist_name != name_jp:
                warnings.append(
                    f"行{i}: 表記揺れを吸収し「{exist_name}」(NO.{existing.get('no')}) に統合"
                )
            elif matched_by == "name_jp_multi":
                warnings.append(
                    f"行{i}: 同名「{name_jp}」が複数登録あり。NO.{existing.get('no')} に更新（要確認）"
                )

        # 住所→都道府県・地域を自動判定
        address = row.get("address", "") or ""
        if address:
            pref, region = address_to_region(address)
        elif existing:
            # 空の住所＋既存あり → 既存の住所を引き継ぐ
            address = existing.get("address", "") or ""
            pref = existing.get("prefecture")
            region = existing.get("region")
        else:
            pref, region = None, None

        # 更新時は空フィールドを既存値でフォールバック
        def _val(key, default=""):
            v = row.get(key)
            if v not in (None, ""):
                return v
            return (existing.get(key, default) if existing else default)

        # custom_hourly_rate: None なら既存値を使う、0以上の数値なら尊重する（0指定を許容）
        new_rate = row.get("custom_hourly_rate")
        try:
            new_rate = int(new_rate) if new_rate not in (None, "") else None
        except (ValueError, TypeError):
            new_rate = None
        if new_rate is None and existing:
            custom_rate = existing.get("custom_hourly_rate")
        else:
            custom_rate = new_rate

        payload = {
            "name_jp": name_jp,  # name_jpは必須なのでそのまま
            "name_en": _val("name_en"),
            "role": _val("role", "Dealer"),
            "contact": _val("contact"),
            "notes": _val("notes"),
            "real_name": _val("real_name"),
            "address": address,
            "email": _val("email"),
            "nearest_station": _val("nearest_station"),
            "employment_type": _val("employment_type", "contractor"),
            "custom_hourly_rate": custom_rate,
            "prefecture": pref,
            "region": region,
        }

        try:
            if existing:
                if no:
                    payload["no"] = no
                payload["updated_at"] = _now()
                client.table("p1_staff").update(payload).eq("id", existing["id"]).execute()
                updated += 1
                # 同一バッチ内の後続行が同じ人物を重複作成しないようインデックス反映
                _index_add(index, {**existing, **payload})
            else:
                if no:
                    payload["no"] = no
                res = client.table("p1_staff").insert(payload).execute()
                created += 1
                new_row = (res.data[0] if getattr(res, "data", None) else dict(payload))
                _index_add(index, new_row)
        except Exception as e:
            errors.append(f"行{i} ({name_jp}): {str(e)[:100]}")

    return {"created": created, "updated": updated, "errors": errors, "warnings": warnings}


def find_or_create_staff(no, name_jp, name_en="", role="Dealer"):
    """NO.（最優先）→ ディーラーネーム(正規化) の順で既存を探し、無ければ作成。

    シフト取込・出退勤から呼ばれる。NO.は一意キーなので NO.一致だけで同一人物と
    みなす（旧実装は NO.＋name_jp の完全一致で、表記揺れ時に NO.重複を生んでいた）。
    NO.未指定/未一致のときだけ、表記揺れを吸収したディーラーネームで照合する。
    """
    client = get_client()
    if no not in (None, ""):
        r = client.table("p1_staff").select("id").eq("no", no).execute()
        if r.data:
            return r.data[0]["id"]
    nk = _norm_key(name_jp)
    if nk:
        r = client.table("p1_staff").select("id, name_jp").execute()
        for s in (r.data or []):
            if _norm_key(s.get("name_jp")) == nk:
                return s["id"]
    return create_staff(no, name_jp, name_en, role)


# === Transport Rules ===

def get_transport_rules(event_id):
    """イベントの地域別交通費ルールを取得"""
    return get_client().table("p1_event_transport_rules").select("*").eq(
        "event_id", event_id).order("region").execute().data


def save_transport_rules(event_id: int, rules: list[dict]):
    """交通費ルールを一括保存（既存削除→再挿入）

    rules: [{"region": "東海", "max_amount": 10000,
            "receipt_required": 1, "is_venue_region": 0, "note": ""}]
    """
    client = get_client()
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
    return get_client().table("p1_transport_claims").select("*").eq(
        "event_id", event_id).execute().data


def upsert_transport_claim(event_id: int, staff_id: int,
                            receipt_amount: int, approved_amount: int,
                            has_receipt: int = 1, note: str = ""):
    """領収書金額を登録/更新"""
    client = get_client()
    existing = client.table("p1_transport_claims").select("id").eq(
        "event_id", event_id).eq("staff_id", staff_id).execute().data
    payload = {
        "event_id": event_id, "staff_id": staff_id,
        "receipt_amount": receipt_amount, "approved_amount": approved_amount,
        "has_receipt": has_receipt, "note": note,
        "updated_at": _now(),
    }
    if existing:
        client.table("p1_transport_claims").update(payload).eq(
            "id", existing[0]["id"]).execute()
    else:
        client.table("p1_transport_claims").insert(payload).execute()


def get_staff_region(staff_id: int):
    """スタッフの地域を取得（address→region優先、未設定時はcontractorデフォルト）"""
    row = get_client().table("p1_staff").select(
        "region, prefecture, address").eq("id", staff_id).execute().data
    if not row:
        return None, None
    return row[0].get("region"), row[0].get("prefecture")


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
    }
    # マイグレ後のカラムは存在チェックして条件付きで投入
    if prefecture and db_schema.has_column("p1_events", "prefecture"):
        payload["prefecture"] = prefecture
    if rate_template_id and db_schema.has_column("p1_events", "rate_template_id"):
        payload["rate_template_id"] = rate_template_id
    r = get_client().table("p1_events").insert(payload).execute()
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
    get_client().table("p1_events").update(payload).eq("id", event_id).execute()


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
    client = get_client()
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
    log_action("bulk_set_rates", "event_rates", event_id,
               detail=f"{len(payload)}日分のレートを一括設定", event_id=event_id)
    return len(payload)


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
    """一括退勤（凍結対応）。対象スタッフIDをリストで返す。"""
    client = get_client()
    affected_staff_ids = []
    for sid in shift_ids:
        row = client.table("p1_shifts").select(
            "planned_start, actual_start, staff_id"
        ).eq("id", sid).execute().data
        if not row:
            continue
        a_start = row[0].get("actual_start") or row[0].get("planned_start")
        affected_staff_ids.append(row[0].get("staff_id"))
        client.table("p1_shifts").update({
            "actual_end": actual_end, "actual_start": a_start, "status": "checked_out"
        }).eq("id", sid).execute()
    if event_id:
        log_action("bulk_checkout", "shifts",
                    detail=f"{len(shift_ids)}名を{actual_end}で一括退勤",
                    event_id=event_id)
    return list({s for s in affected_staff_ids if s is not None})


def reset_payment_to_pending(event_id, staff_id, reason="凍結再計算"):
    """支払いを未承認に戻す（凍結発生時の再計算準備）。

    支払済み(paid)は保護。承認済み(approved)→未承認(pending)に戻す。
    Returns: True=リセット成功、False=支払済みで保護 or レコードなし
    """
    client = get_client()
    existing = client.table("p1_payments").select("id, status").eq(
        "event_id", event_id).eq("staff_id", staff_id).execute().data
    if not existing:
        return False
    payment = existing[0]
    if payment["status"] == "paid":
        log_action("freeze_recalc_skipped", "payments", payment["id"],
                    detail=f"{reason}: 支払済みのため保護", event_id=event_id)
        return False
    client.table("p1_payments").update({
        "status": "pending", "approved_by": None, "approved_at": None,
    }).eq("id", payment["id"]).execute()
    log_action("freeze_recalc", "payments", payment["id"],
                detail=f"{reason}: 未承認に戻した", event_id=event_id)
    return True


def mark_absent(shift_id):
    get_client().table("p1_shifts").update({
        "status": "absent", "actual_start": None, "actual_end": None
    }).eq("id", shift_id).execute()


def set_shift_mix(shift_id, is_mix):
    get_client().table("p1_shifts").update({"is_mix": is_mix}).eq("id", shift_id).execute()


# === Payments ===

def rounding_supported() -> bool:
    """端数処理(payable_amount/rounding_unit)のマイグレが適用済みか。

    未適用だと rounding_unit を保存できず payable_amount も計算できないため、
    UI 側で端数処理セレクタを無効化する判定に使う（無限リランの防止）。
    """
    from utils import db_schema
    return (db_schema.has_column("p1_events", "rounding_unit")
            and db_schema.has_column("p1_payments", "payable_amount"))


def get_event_rounding_unit(event_id) -> int:
    """イベントの端数処理単位（0=なし/100/500/1000）を返す。

    A-6 (2026-06-01): payable_amount 算出に使う。rounding_unit 列が未適用の環境では 0。
    """
    from utils import db_schema
    if not db_schema.has_column("p1_events", "rounding_unit"):
        return 0
    row = get_client().table("p1_events").select("rounding_unit").eq(
        "id", event_id).execute().data
    try:
        return int(row[0].get("rounding_unit") or 0) if row else 0
    except (TypeError, ValueError):
        return 0


def compute_payable_amount(total_amount: int, rounding_unit: int) -> int:
    """支払確定額（丸め後）を返す。rounding_unit=0 なら total そのまま（ゼロ除算回避）。"""
    from utils.denomination import round_amount
    ru = int(rounding_unit or 0)
    if ru <= 0:
        return int(total_amount)
    return round_amount(int(total_amount), ru)


def get_payable(payment: dict) -> int:
    """支払レコードから「実際に支払う確定額」を取り出す（A-6 の唯一の正）。

    payable_amount 列があればそれを、無い/NULL の旧行は total_amount を代替値とする。
    封筒・領収書・年間累計・精算レポート・ピット端末はすべてこの関数を通して金額を表示する。
    """
    if payment is None:
        return 0
    val = payment.get("payable_amount")
    if val is None:
        val = payment.get("total_amount", 0)
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def save_payment(event_id, staff_id, base_pay, night_pay, transport_total,
                 floor_bonus_total, mix_bonus_total, attendance_bonus,
                 total_amount, break_deduction=0, adjustment=0, adjustment_note="",
                 individual_allowance_total: int = 0):
    """支払いレコードを保存（既存の pending/approved は削除して上書き、paid は保護）

    Codex P2 fix #3 (2026-05-09): individual_allowance_total を追加
    （個別手当の合計を保存して、内訳と合計の整合性を確保）
    A-5/A-6 (2026-06-01):
      - total_amount は adjustment（臨時調整）込みで渡される前提（calculator が含める）。
      - payable_amount = round(total_amount, event.rounding_unit) を算出して保存し、
        封筒・領収書・年間累計が同じ確定額を参照できるようにする。
      - 再計算で手入力メモ(notes)が消えないよう、既存 notes を読み出して引き継ぐ。
    マイグレ未実行時は db_schema.has_column チェックでスキップする後方互換あり。
    """
    from utils import db_schema
    client = get_client()
    # notes 列はマイグレ未適用の環境では存在しないため、SELECT も条件付きで組む
    # （無条件に notes を select すると古いDBで save_payment 自体が失敗する）。
    _has_notes = db_schema.has_column("p1_payments", "notes")
    _sel = "id, status, notes" if _has_notes else "id, status"
    existing = client.table("p1_payments").select(_sel).eq(
        "event_id", event_id).eq("staff_id", staff_id).execute()
    existing_notes = ""
    if existing.data:
        if existing.data[0]["status"] == "paid":
            return  # 支払済みは上書きしない
        # A-5: 再計算で消えないよう手入力メモを退避
        existing_notes = existing.data[0].get("notes") or "" if _has_notes else ""
        client.table("p1_payments").delete().eq("id", existing.data[0]["id"]).execute()
    payload = {
        "event_id": event_id, "staff_id": staff_id,
        "base_pay": base_pay, "night_pay": night_pay, "transport_total": transport_total,
        "floor_bonus_total": floor_bonus_total, "mix_bonus_total": mix_bonus_total,
        "attendance_bonus": attendance_bonus, "break_deduction": break_deduction,
        "adjustment": adjustment, "adjustment_note": adjustment_note,
        "total_amount": total_amount,
    }
    # A-5: 手入力メモを引き継ぐ（notes 列がある場合のみ）
    if existing_notes and db_schema.has_column("p1_payments", "notes"):
        payload["notes"] = existing_notes
    if individual_allowance_total and db_schema.has_column(
        "p1_payments", "individual_allowance_total"
    ):
        payload["individual_allowance_total"] = int(individual_allowance_total)
    # A-6: 支払確定額（丸め後）を保存
    if db_schema.has_column("p1_payments", "payable_amount"):
        payload["payable_amount"] = compute_payable_amount(
            total_amount, get_event_rounding_unit(event_id)
        )
    client.table("p1_payments").insert(payload).execute()
    log_action("calculate_payment", "payments", staff_id, f"合計¥{total_amount:,}", event_id)


def set_payment_adjustment(payment_id, adjustment, adjustment_note="",
                            event_id=None, performed_by="system"):
    """既存支払いの臨時調整額(adjustment)だけを更新する（A-5 の編集UI用）。

    シフトからの再計算をせず、total_amount/payable_amount を整合させて差し替える:
        components = 旧 total_amount - 旧 adjustment
        新 total   = components + 新 adjustment
    paid は保護（変更不可）。Returns: True=更新成功 / False=支払済み or レコードなし。
    """
    from utils import db_schema
    client = get_client()
    row = client.table("p1_payments").select(
        "status, total_amount, adjustment").eq("id", payment_id).execute().data
    if not row:
        return False
    # 臨時調整の編集は未承認(pending)のみ許可（UIと一致）。承認/支払済みは再承認を
    # 経るべきなので、ここでブロックする。並走で承認/支払されても下の status 述語で原子的に弾く。
    if row[0].get("status") != "pending":
        return False
    old_total = int(row[0].get("total_amount") or 0)
    old_adj = int(row[0].get("adjustment") or 0)
    try:
        new_adj = int(adjustment or 0)
    except (TypeError, ValueError):
        new_adj = 0
    new_total = (old_total - old_adj) + new_adj
    payload = {
        "adjustment": new_adj,
        "adjustment_note": adjustment_note or "",
        "total_amount": new_total,
    }
    if db_schema.has_column("p1_payments", "payable_amount"):
        payload["payable_amount"] = compute_payable_amount(
            new_total, get_event_rounding_unit(event_id) if event_id else 0
        )
    # A-6: 金額が変わったら、既発行の領収書（PDF/トークン）と受領フラグを無効化する。
    # 旧額の領収書が再利用される・旧額のまま支払われるのを防ぐ（要再発行）。
    if new_total != old_total:
        if db_schema.has_column("p1_payments", "receipt_received"):
            payload["receipt_received"] = 0
        if db_schema.has_column("p1_payments", "receipt_pdf_path"):
            payload["receipt_pdf_path"] = None
            payload["receipt_token"] = None
            if db_schema.has_column("p1_payments", "receipt_token_expires_at"):
                payload["receipt_token_expires_at"] = None
    # TOCTOU 対策: フォーム表示中に他セッションが承認/支払した場合に備え、
    # status=pending を述語に含めて原子的に更新する。0件なら変更が起きなかったとして False。
    res = client.table("p1_payments").update(payload).eq(
        "id", payment_id).eq("status", "pending").execute()
    if not res.data:
        return False
    log_action("set_adjustment", "payments", payment_id,
               f"臨時調整 ¥{new_adj:,}（{adjustment_note or '—'}）→ 合計¥{new_total:,}"
               + ("／領収書無効化" if new_total != old_total else ""),
               event_id, performed_by=performed_by)
    return True


def recompute_payable_for_event(event_id, rounding_unit=None):
    """イベント内の未払い(pending/approved)支払いの payable_amount を再計算する（A-6）。

    端数処理単位を変えたとき、全件のシフト再計算をせず、保存済み total_amount を
    新しい単位で丸め直すだけで封筒・領収書・年間累計を整合させる。
    paid は確定済みのため触らない。Returns: 更新した件数。
    """
    from utils import db_schema
    if not db_schema.has_column("p1_payments", "payable_amount"):
        return 0
    ru = get_event_rounding_unit(event_id) if rounding_unit is None else int(rounding_unit or 0)
    client = get_client()
    # receipt 列があれば、確定額が変わった行の旧領収書を無効化するため一緒に取得
    _has_receipt = db_schema.has_column("p1_payments", "receipt_pdf_path")
    cols = "id, total_amount, payable_amount, status"
    if _has_receipt:
        cols += ", receipt_pdf_path, receipt_token"
    rows = client.table("p1_payments").select(cols).eq("event_id", event_id).execute().data
    n = 0
    invalidated = 0
    reverted = 0
    for r in rows:
        if r.get("status") == "paid":
            continue
        new_payable = compute_payable_amount(r.get("total_amount") or 0, ru)
        update = {"payable_amount": new_payable}
        # A-6: 確定額が変わったのに旧領収書PDF/トークン/受領フラグが残っていると、
        # PDFの額面・支払い可否ゲートが旧額のままになる。発行済みなら無効化して再発行を促す。
        changed = int(r.get("payable_amount") or r.get("total_amount") or 0) != int(new_payable)
        _did_invalidate = False
        _did_revert = False
        if changed:
            # 受領フラグは旧額に対するものなのでリセット（支払いゲートを再確認させる）
            if db_schema.has_column("p1_payments", "receipt_received"):
                update["receipt_received"] = 0
            if _has_receipt and (r.get("receipt_pdf_path") or r.get("receipt_token")):
                update["receipt_pdf_path"] = None
                update["receipt_token"] = None
                if db_schema.has_column("p1_payments", "receipt_token_expires_at"):
                    update["receipt_token_expires_at"] = None
                _did_invalidate = True
            # 内部統制: 承認済みの金額が変わったら再承認を必須化（未承認へ差し戻し）。
            # 通常の再計算が approved を保護するのと整合させ、無承認での金額変更を防ぐ。
            if r.get("status") == "approved":
                update["status"] = "pending"
                update["approved_by"] = None
                update["approved_at"] = None
                _did_revert = True
        # TOCTOU 対策: select 後に他セッションが status を変えた（特に paid 化）場合に
        # 上書き・差し戻ししないよう、観測した status を述語に含めて原子的に更新する。
        res = client.table("p1_payments").update(update).eq(
            "id", r["id"]).eq("status", r.get("status")).execute()
        if res.data:
            n += 1
            # 実際に書き込めた行だけカウント（並走で弾かれた行は数えない）
            if _did_invalidate:
                invalidated += 1
            if _did_revert:
                reverted += 1
    if invalidated or reverted:
        log_action(
            "invalidate_receipts_rounding", "payments", None,
            detail=(f"端数処理変更: 領収書無効化 {invalidated} 件 / "
                    f"承認差し戻し {reverted} 件（要再承認・再発行）"),
            event_id=event_id,
        )
    return {"updated": n, "invalidated": invalidated, "reverted": reverted}


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
        # A-6: 年間累計も支払確定額(payable_amount)で集計し、封筒/領収書と一致させる。
        _amt = get_payable(p)
        totals[s_id]["total_amount"] += _amt
        if p.get("status") == "paid":
            totals[s_id]["paid_amount"] += _amt
        totals[s_id]["event_count"] += 1
        totals[s_id]["event_names"].add(event_name_map.get(p["event_id"], ""))

    # setをlistに変換
    result = []
    for v in totals.values():
        v["event_names"] = sorted(v["event_names"])
        result.append(v)
    return sorted(result, key=lambda x: -x["total_amount"])


def approve_payment(payment_id, approved_by, event_id=None):
    """pending → approved のみ許可（状態遷移ガード）。

    A-3/A-9 (2026-06-01): `.eq("status","pending")` を付与し、
    承認スキップ（pending以外をいきなり承認）・並走競合・逆行を防ぐ。
    Returns: True=承認できた / False=pending以外（既に承認/支払済 or 競合）で変化なし。
    """
    res = get_client().table("p1_payments").update({
        "status": "approved", "approved_by": approved_by, "approved_at": _now()
    }).eq("id", payment_id).eq("status", "pending").execute()
    changed = bool(res.data)
    if changed:
        log_action("approve_payment", "payments", payment_id,
                   f"承認者: {approved_by}", event_id, performed_by=approved_by)
    else:
        log_action("approve_payment_noop", "payments", payment_id,
                   "pending以外のため承認スキップ（状態不一致/競合）",
                   event_id, performed_by=approved_by)
    return changed


def mark_paid(payment_id, event_id=None, performed_by="system"):
    """approved → paid のみ許可（状態遷移ガード）＋支払実行者を記録。

    A-2 (2026-06-01): performed_by を監査ログと paid_by 列（has_column 後方互換）に記録。
        現金確定という最も不可逆な操作の実行者を追跡可能にする。
    A-3/A-9: `.eq("status","approved")` を付与し、承認スキップ・paid二重化・
        並走競合（TOCTOU）を DB 条件側でブロックする。
    Returns: True=支払済にできた / False=approved以外（既に支払済 or 競合）で変化なし。
    """
    from utils import db_schema
    payload = {"status": "paid", "paid_at": _now()}
    if performed_by and db_schema.has_column("p1_payments", "paid_by"):
        payload["paid_by"] = str(performed_by)
    res = get_client().table("p1_payments").update(payload).eq(
        "id", payment_id).eq("status", "approved").execute()
    changed = bool(res.data)
    if changed:
        log_action("mark_paid", "payments", payment_id,
                   f"支払実行: {performed_by}", event_id, performed_by=performed_by)
    else:
        log_action("mark_paid_noop", "payments", payment_id,
                   "approved以外のため支払スキップ（状態不一致/競合）",
                   event_id, performed_by=performed_by)
    return changed


def mark_receipt_received(payment_id, event_id=None, performed_by="system"):
    """領収書受領フラグを立てる。A-2: 実行者を監査ログに記録。"""
    get_client().table("p1_payments").update({"receipt_received": 1}).eq("id", payment_id).execute()
    log_action("receipt_received", "payments", payment_id, "", event_id, performed_by=performed_by)


# === Individual Allowances (Phase 3-I, 2026-05-08) ===

def get_individual_allowances(event_id: int, staff_id: Optional[int] = None) -> list:
    """個別手当を取得

    Args:
        event_id: 対象イベント
        staff_id: 指定すればそのスタッフのみ。Noneなら全員分

    Returns:
        [{id, event_id, staff_id, allowance_type, label, amount,
          is_off_record, note, created_at, created_by}, ...]

    マイグレ未実行時は空リストを返す（後方互換）。
    """
    from utils import db_schema
    if not db_schema.has_column("p1_staff_event_allowances", "id"):
        return []
    q = get_client().table("p1_staff_event_allowances").select(
        "*").eq("event_id", event_id)
    if staff_id is not None:
        q = q.eq("staff_id", staff_id)
    return q.execute().data or []


def add_individual_allowance(event_id: int, staff_id: int,
                              allowance_type: str, amount: int,
                              label: str = "", is_off_record: int = 0,
                              note: str = "", created_by: str = "system") -> Optional[int]:
    """個別手当を1件追加

    Args:
        allowance_type: "language" / "recruitment" / "leadership" / "other"
        amount: 円単位
        is_off_record: 1 なら ピット端末で内訳非表示
    Returns:
        作成された ID（マイグレ未実行時は None）
    """
    from utils import db_schema
    if not db_schema.has_column("p1_staff_event_allowances", "id"):
        return None
    r = get_client().table("p1_staff_event_allowances").insert({
        "event_id": event_id, "staff_id": staff_id,
        "allowance_type": allowance_type,
        "label": label or _allowance_default_label(allowance_type),
        "amount": int(amount),
        "is_off_record": int(is_off_record),
        "note": note,
        "created_by": created_by,
    }).execute()
    aid = r.data[0]["id"] if r.data else None
    if aid:
        log_action(
            "add_individual_allowance", "allowances", aid,
            detail=f"{allowance_type} ¥{amount:,}"
            + (" (オフレコ)" if is_off_record else ""),
            event_id=event_id, performed_by=created_by,
        )
    return aid


def remove_individual_allowance(allowance_id: int, event_id: Optional[int] = None,
                                 performed_by: str = "system") -> bool:
    """個別手当を1件削除"""
    from utils import db_schema
    if not db_schema.has_column("p1_staff_event_allowances", "id"):
        return False
    get_client().table("p1_staff_event_allowances").delete().eq(
        "id", allowance_id).execute()
    log_action(
        "remove_individual_allowance", "allowances", allowance_id,
        detail="削除", event_id=event_id, performed_by=performed_by,
    )
    return True


def _allowance_default_label(allowance_type: str) -> str:
    """allowance_type からデフォルトラベル"""
    return {
        "language": "言語手当",
        "recruitment": "人材確保手当",
        "leadership": "リーダー手当",
        "other": "個別手当",
    }.get(allowance_type, "個別手当")


# === Petty Cash ===

def add_petty_cash(event_id, date, description, amount, requester, approver="",
                   account_code: str = "", payee_name: str = ""):
    """小口経費を追加

    v3.8 (2026-05-08) で account_code（勘定科目）と payee_name（領収書宛名）を追加。
    マイグレーション 20260508_add_petty_cash_accounting.sql 未実行時は無視される
    （後方互換）。
    """
    from utils import db_schema
    payload = {
        "event_id": event_id, "date": date, "description": description,
        "amount": amount, "requester": requester, "approver": approver,
    }
    # 後方互換: マイグレ後のカラムは存在チェックして条件付きで投入
    if account_code and db_schema.has_column("p1_petty_cash", "account_code"):
        payload["account_code"] = account_code
    if payee_name and db_schema.has_column("p1_petty_cash", "payee_name"):
        payload["payee_name"] = payee_name
    get_client().table("p1_petty_cash").insert(payload).execute()
    log_action(
        "add_petty_cash", "petty_cash",
        detail=f"¥{amount:,} {description}"
        + (f" [{account_code}]" if account_code else ""),
        event_id=event_id,
    )


def get_petty_cash_for_event(event_id):
    return get_client().table("p1_petty_cash").select("*").eq("event_id", event_id).order("date").order("created_at").execute().data


# === 互換性のためのinit_db（何もしない） ===
def init_db():
    pass


# =====================================================================
# ディーラー応募GSS連動（案A）— service_role 経路 + 応募テーブル/対応表
#   応募テーブルは PII を含み RLS で anon 全拒否のため、anon キーでは読めない。
#   サーバ側 service_role（SUPABASE_SERVICE_KEY）でのみアクセスする。
#   未設定時は applications_enabled()=False を返し、画面側はグレースフルに案内する。
# =====================================================================
DEALER_APP_TABLE = "p1_dealer_applications"
APP_SOURCES_TABLE = "p1_application_sources"


def _get_service_supabase_config():
    """service_role 用 URL/Key。SERVICE_KEY が無ければ None。

    SERVICE_KEY だけ独立に読み、URL は通常設定（_get_supabase_config: secrets>env>
    デフォルトURL）を再利用する。これにより URL を二重に設定しなくても、
    SERVICE_KEY を足すだけで応募連動を有効化できる。
    """
    # SERVICE_KEY / SERVICE_ROLE_KEY（標準名・Edge側と統一）のどちらでも受理する。
    key = None
    for _name in ("SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        try:
            v = st.secrets.get(_name)
        except Exception:
            v = None
        if not v:
            v = os.environ.get(_name)
        if v:
            key = str(v)
            break
    if not key:
        return None
    try:
        url, _anon = _get_supabase_config()
    except Exception:
        url = None
    if not url:
        return None
    return str(url), str(key)


def get_service_client():
    """service_role クライアント（応募PIIテーブル等・RLSバイパス）。未設定なら None。"""
    cfg = _get_service_supabase_config()
    if not cfg:
        return None
    return create_client(cfg[0], cfg[1])


def _supabase_key_role(token: str):
    """Supabaseキー(JWT)の role クレームを返す。JWTでない/解析不可なら None。

    旧形式キーは JWT で role=anon / service_role を持つ。新形式の不透明キー
    （sb_secret_ 等）は JWT でないため None を返す（その場合は role 判定をスキップ）。
    """
    try:
        import base64
        import json
        parts = (token or "").split(".")
        if len(parts) != 3:
            return None
        pad = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        return payload.get("role")
    except Exception:
        return None


def applications_enabled() -> bool:
    """応募連動が使える状態か（service_role キーが設定され、応募テーブルが存在する）。"""
    cfg = _get_service_supabase_config()
    if cfg is None:
        return False
    _url, key = cfg
    role = _supabase_key_role(key)
    if role is not None:
        # 旧形式JWT: service_role 以外（anon等）の誤設定は有効化しない。
        if role != "service_role":
            return False
    elif str(key).startswith("sb_publishable_"):
        # 新形式の publishable キー（anon相当）の誤設定 → 有効化しない。
        # （RLS で空読みになり「有効に見えるが読めない/書けない」誤動作を防ぐ）
        return False
    # それ以外（sb_secret_ や不明な不透明キー）は下の probe で確認する。
    try:
        get_service_client().table(DEALER_APP_TABLE).select("id").limit(1).execute()
        return True
    except Exception:
        return False


def get_application_sources():
    """大会↔GSS 対応表（全件・新しい順）。未設定/失敗時は空リスト。"""
    c = get_service_client()
    if c is None:
        return []
    try:
        return c.table(APP_SOURCES_TABLE).select("*").order("id", desc=True).execute().data or []
    except Exception:
        return []


def add_application_source(event_id: int, label: str, spreadsheet_id: str,
                           sheet_name: str = "フォームの回答 1"):
    """大会↔GSS 対応を登録。"""
    c = get_service_client()
    if c is None:
        raise RuntimeError("SUPABASE_SERVICE_KEY が未設定です")
    return c.table(APP_SOURCES_TABLE).insert({
        "event_id": event_id,
        "label": (label or "").strip() or None,
        "spreadsheet_id": spreadsheet_id.strip(),
        "sheet_name": (sheet_name or "").strip() or "フォームの回答 1",
        "is_active": True,
    }).execute().data


def set_source_active(source_id: int, active: bool):
    """対応の有効/無効を切り替え。"""
    c = get_service_client()
    if c is None:
        raise RuntimeError("SUPABASE_SERVICE_KEY が未設定です")
    now = datetime.now(timezone(timedelta(hours=9))).isoformat()
    c.table(APP_SOURCES_TABLE).update(
        {"is_active": bool(active), "updated_at": now}
    ).eq("id", source_id).execute()


def get_dealer_applications(event_id=None, statuses=None):
    """応募一覧（任意で大会・ステータス絞り込み）。未設定/失敗時は空リスト。"""
    c = get_service_client()
    if c is None:
        return []
    try:
        q = c.table(DEALER_APP_TABLE).select("*")
        if event_id is not None:
            q = q.eq("event_id", event_id)
        if statuses:
            q = q.in_("status", list(statuses))
        return q.order("applied_at", desc=True).execute().data or []
    except Exception:
        return []


def promote_dealer_application(app_id: int, operator: str,
                               prefecture=None, region=None):
    """応募を採用＝p1_staff へ昇格（RPC・トランザクション）。staff_id を返す。"""
    c = get_service_client()
    if c is None:
        raise RuntimeError("SUPABASE_SERVICE_KEY が未設定です")
    res = c.rpc("promote_dealer_application", {
        "p_app_id": app_id,
        "p_operator": operator,
        "p_prefecture": prefecture,
        "p_region": region,
    }).execute()
    return res.data


def reject_dealer_application(app_id: int, operator: str):
    """応募を不採用に（人手判定済みのものは触らない＝new/reviewed/source_changedのみ）。"""
    c = get_service_client()
    if c is None:
        raise RuntimeError("SUPABASE_SERVICE_KEY が未設定です")
    now = datetime.now(timezone(timedelta(hours=9))).isoformat()
    c.table(DEALER_APP_TABLE).update(
        {"status": "rejected", "reviewed_by": operator, "updated_at": now}
    ).eq("id", app_id).in_("status", ["new", "reviewed", "source_changed"]).execute()


def log_action_service(action, target_type, target_id=None, detail="",
                       event_id=None, performed_by="system") -> bool:
    """監査ログを service_role で記録（応募PIIページ等）。

    anon が p1_audit_log に書けない構成でも確実に残すため service client を使う。
    成功なら True を返す（呼び出し側は成功時のみ「記録済み」フラグを立て、
    失敗時は次回再試行できる）。service client が無ければ anon の log_action に委譲。
    """
    c = get_service_client()
    if c is None:
        log_action(action, target_type, target_id=target_id, detail=detail,
                   event_id=event_id, performed_by=performed_by)
        return True
    try:
        c.table("p1_audit_log").insert({
            "event_id": event_id, "action": action, "target_type": target_type,
            "target_id": target_id, "detail": detail, "performed_by": performed_by,
        }).execute()
        return True
    except Exception:
        return False
