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
# 2026-07-29: 接続情報のハードコードを廃止。
# 従来は実プロジェクトのURLとanonキーを直書きし、未設定時に黙ってそこへ
# フォールバックしていたため、①公開リポジトリとイメージにキーが焼き込まれる
# ②本番で設定漏れに気づけない、という二重の問題があった。
# 現在は未設定なら明示的に失敗させる（fail closed）。
_DEFAULT_SUPABASE_URL = ""
_DEFAULT_SUPABASE_KEY = ""


def _sanitize_key(raw) -> str:
    """Secretsに貼られたキーの貼り付け事故を吸収する（2026-07-28 追加）。

    - 前後の空白・引用符を除去
    - JWT（eyJ〜）や新形式キー（sb_〜）の内部に紛れた改行・空白を除去
      （Secretsのテキストエリアで折り返し貼り付けした場合の破損対策）
    """
    s = str(raw or "").strip().strip('"').strip("'").strip()
    if s.startswith("eyJ") or s.startswith("sb_"):
        s = "".join(s.split())
    return s


def supabase_key_role(token: str):
    """キー(JWT)の role クレームを返す。JWTでない/解析不可なら None。

    旧形式キーは JWT で role=anon / service_role を持つ。新形式の不透明キー
    （sb_secret_ 等）は JWT でないため None（role判定スキップ）。
    """
    try:
        import base64
        import json as _json
        parts = (token or "").split(".")
        if len(parts) != 3:
            return None
        pad = "=" * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        return payload.get("role")
    except Exception:
        return None


def _get_supabase_config():
    """Supabase URL/Keyを取得。

    Key優先度: SUPABASE_SERVICE_KEY > SUPABASE_SERVICE_ROLE_KEY > SUPABASE_KEY(anon)
    > 環境変数 > デフォルトanon。
    Streamlitはサーバ側で動くため service_role キーを使ってもブラウザに露出しない。
    SUPABASE_SERVICE_KEY を設定すればアプリ全体が service_role で動くので、PIIテーブルの
    anon権限を締めても壊れない。未設定時は従来どおり anon にフォールバック
    （※anon権限剥奪後はSecrets設定が必須になる）。
    """
    def _secret(name):
        try:
            return st.secrets.get(name)
        except Exception:
            return None

    url = _sanitize_key(_secret("SUPABASE_URL") or os.environ.get("SUPABASE_URL", _DEFAULT_SUPABASE_URL))
    key = _sanitize_key(
        _secret("SUPABASE_SERVICE_KEY")
        or _secret("SUPABASE_SERVICE_ROLE_KEY")
        or _secret("SUPABASE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY", _DEFAULT_SUPABASE_KEY)
    )
    return url, key


def connection_health() -> dict:
    """DB接続の健全性診断（発行者設定ページの管理者向け表示・移行確認用 2026-07-28）。

    Returns: {"role": 接続キーのロール名（service_role / anon / opaque）,
              "using_default_key": bool, "select_ok": bool, "error": str}
    """
    url, key = _get_supabase_config()
    role = supabase_key_role(key) or ("opaque(sb_*)" if key.startswith("sb_") else "不明")
    # 既定キーは廃止済み（空）。空同士の比較で「既定キー使用」と誤判定しないようにする
    using_default = bool(_DEFAULT_SUPABASE_KEY) and (key == _sanitize_key(_DEFAULT_SUPABASE_KEY))
    out = {"role": role, "using_default_key": using_default, "select_ok": False,
           "ok": False, "error": ""}
    try:
        get_client().table("p1_events").select("id").limit(1).execute()
        out["select_ok"] = True
        out["ok"] = True   # 起動時セルフテストが参照するキー名（select_ok と同義）
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


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


def _revert_payment_if_amount_affected(shift_row, reason: str) -> None:
    """出退勤の実績変更が支払い額に影響し得るとき、計算済みの支払いを未承認に戻す。

    凍結退勤と同じ内部統制（reset_payment_to_pending。支払済みは保護）を
    欠勤・遅刻・早退・延長にも適用する（2026-07-06 追加）。
    支払い未計算・列欠損などの失敗は握りつぶし、本処理（打刻）は壊さない。
    """
    try:
        ev = shift_row.get("event_id")
        sid = shift_row.get("staff_id")
        if ev and sid:
            reset_payment_to_pending(ev, sid, reason=reason)
    except Exception:
        pass


def checkin_staff(shift_id, actual_start):
    client = get_client()
    row = client.table("p1_shifts").select(
        "status, actual_end, planned_start, event_id, staff_id"
    ).eq("id", shift_id).execute().data
    if row and row[0].get("actual_end"):
        client.table("p1_shifts").update({"actual_start": actual_start}).eq("id", shift_id).execute()
    else:
        client.table("p1_shifts").update({
            "actual_start": actual_start, "status": "checked_in"
        }).eq("id", shift_id).execute()
    # 予定と違う到着時刻（遅刻等）は支払い額が変わるため、承認済みを差し戻す
    if row and str(actual_start) != str(row[0].get("planned_start")):
        _revert_payment_if_amount_affected(row[0], reason=f"到着実績 {actual_start} 記録（要再計算）")


def checkout_staff(shift_id, actual_end):
    client = get_client()
    row = client.table("p1_shifts").select(
        "planned_end, event_id, staff_id"
    ).eq("id", shift_id).execute().data
    client.table("p1_shifts").update({
        "actual_end": actual_end, "status": "checked_out"
    }).eq("id", shift_id).execute()
    # 予定と違う退勤時刻（早退・延長）は支払い額が変わるため、承認済みを差し戻す
    if row and str(actual_end) != str(row[0].get("planned_end")):
        _revert_payment_if_amount_affected(row[0], reason=f"退勤実績 {actual_end} 記録（要再計算）")


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


# ============================================================
# 弁当配布チェック（2026-06-18 追加）
# ============================================================
# 大会期間中の弁当配布を「シフト1人1日」単位で管理する。
# マイグレ docs/db_migrations/20260618_add_lunch_status.sql 必須。
# 列が無い古いDBでも壊れないよう、UPDATE は失敗時に静かに無視する。
LUNCH_STATUSES = ("pending", "received", "cancelled")


def _validate_lunch_status(status: str) -> str:
    """状態文字列のバリデーション（不正値は例外）。

    'received'：配布済 ／ 'cancelled'：辞退 ／ 'pending'：未受領（既定）
    """
    s = (status or "").strip().lower()
    if s not in LUNCH_STATUSES:
        raise ValueError(f"lunch_status は {LUNCH_STATUSES} のいずれか（指定: {status!r}）")
    return s


def update_lunch_status(shift_id, status: str, performed_by: str = "") -> bool:
    """1つのシフトの弁当配布状態を更新。

    Returns: True=更新成功（or 既に同状態）、False=列未追加・対象なし等で失敗
    """
    s = _validate_lunch_status(status)
    try:
        get_client().table("p1_shifts").update({
            "lunch_status": s,
            "lunch_status_at": _now(),
            "lunch_status_by": (performed_by or "")[:40],
        }).eq("id", shift_id).execute()
        return True
    except Exception:
        # 列が無い古いDB等：マイグレ未実行を呼び出し側で検知できるよう False を返す
        return False


def bulk_set_lunch_status(event_id, date, status: str, performed_by: str = "") -> int:
    """指定イベント×日付の出勤予定者全員に同じ状態を設定。

    欠勤者（status='absent'）は対象外。
    Returns: 更新対象だったシフト数（実反映件数。失敗時は 0）。
    """
    s = _validate_lunch_status(status)
    client = get_client()
    try:
        rows = client.table("p1_shifts").select("id").eq(
            "event_id", event_id).eq("date", date).neq("status", "absent").execute().data or []
        for r in rows:
            client.table("p1_shifts").update({
                "lunch_status": s,
                "lunch_status_at": _now(),
                "lunch_status_by": (performed_by or "")[:40],
            }).eq("id", r["id"]).execute()
        log_action("bulk_set_lunch_status", "shifts",
                   detail=f"{date} の {len(rows)}名を {s} に設定",
                   event_id=event_id, performed_by=(performed_by or "system"))
        return len(rows)
    except Exception:
        return 0


def get_lunch_summary(event_id, date) -> dict:
    """指定イベント×日付の弁当配布サマリ。

    Returns: {"received": N, "pending": N, "cancelled": N, "total_active": N}
       total_active = 出勤予定者数（欠勤除外）。
    """
    client = get_client()
    try:
        rows = client.table("p1_shifts").select(
            "lunch_status, status"
        ).eq("event_id", event_id).eq("date", date).execute().data or []
    except Exception:
        return {"received": 0, "pending": 0, "cancelled": 0, "total_active": 0}
    out = {"received": 0, "pending": 0, "cancelled": 0, "total_active": 0}
    for r in rows:
        if (r.get("status") or "") == "absent":
            continue
        out["total_active"] += 1
        ls = (r.get("lunch_status") or "pending").lower()
        if ls in out:
            out[ls] += 1
    return out


# ============================================================
# 配布チェック汎用（弁当2個目・ドリンクチケット 2026-07-02 追加）
# ============================================================
# lunch  : 弁当1個目（20260618 既存列 lunch_status）
# lunch2 : 弁当2個目。12時間以上の予定シフト者のみUIに表示
# drink  : ドリンクチケット（一律2枚＝配布済みかの1チェック）
# マイグレ docs/db_migrations/20260702_add_lunch2_drink_status.sql 必須。
# 列が無い古いDBでも壊れないよう、失敗は False / 0 で返す（lunch関数と同じ流儀）。
DISTRIBUTION_KINDS = {
    "lunch": "lunch_status",
    "lunch2": "lunch2_status",
    "drink": "drink_status",
}

# 弁当2個目の対象となる予定シフト時間（分）
LUNCH2_THRESHOLD_MINUTES = 12 * 60


def planned_shift_minutes(planned_start, planned_end) -> int:
    """予定シフトの拘束時間（分）。'26:00' 等の24時超え表記に対応。不正値は0。"""
    try:
        h1, m1 = map(int, str(planned_start).strip().split(":"))
        h2, m2 = map(int, str(planned_end).strip().split(":"))
        return max(0, (h2 * 60 + m2) - (h1 * 60 + m1))
    except (ValueError, AttributeError):
        return 0


def _distribution_column(kind: str) -> str:
    col = DISTRIBUTION_KINDS.get((kind or "").strip().lower())
    if not col:
        raise ValueError(f"kind は {tuple(DISTRIBUTION_KINDS)} のいずれか（指定: {kind!r}）")
    return col


def update_distribution_status(shift_id, kind: str, status: str, performed_by: str = "") -> bool:
    """1つのシフトの配布状態（弁当2個目/ドリンク等）を更新。

    Returns: True=更新成功、False=列未追加（マイグレ未実行）等で失敗
    """
    col = _distribution_column(kind)
    s = _validate_lunch_status(status)
    try:
        get_client().table("p1_shifts").update({
            col: s,
            f"{col}_at": _now(),
            f"{col}_by": (performed_by or "")[:40],
        }).eq("id", shift_id).execute()
        return True
    except Exception:
        return False


def bulk_set_distribution_status(event_id, date, kind: str, status: str,
                                 performed_by: str = "") -> int:
    """指定イベント×日付の出勤予定者全員に同じ配布状態を設定（欠勤者除外）。

    Returns: 実反映件数（失敗時は 0）。
    """
    col = _distribution_column(kind)
    s = _validate_lunch_status(status)
    client = get_client()
    try:
        rows = client.table("p1_shifts").select("id").eq(
            "event_id", event_id).eq("date", date).neq("status", "absent").execute().data or []
        for r in rows:
            client.table("p1_shifts").update({
                col: s,
                f"{col}_at": _now(),
                f"{col}_by": (performed_by or "")[:40],
            }).eq("id", r["id"]).execute()
        log_action(f"bulk_set_{kind}_status", "shifts",
                   detail=f"{date} の {len(rows)}名を {s} に設定",
                   event_id=event_id, performed_by=(performed_by or "system"))
        return len(rows)
    except Exception:
        return 0


def get_handout_summary(event_id, date) -> dict:
    """指定イベント×日付の配布サマリ（弁当1・弁当2・ドリンクをまとめて1クエリで）。

    Returns:
        {"lunch": {...}, "lunch2": {...}, "drink": {...},
         "total_active": N, "migrated": bool}
        migrated=False は lunch2/drink 列が未追加（マイグレ未実行）。
        その場合 lunch2/drink はゼロ埋め・lunch のみ有効。
    """
    client = get_client()
    empty = {"received": 0, "pending": 0, "cancelled": 0}
    out = {"lunch": dict(empty), "lunch2": dict(empty), "drink": dict(empty),
           "total_active": 0, "migrated": True}
    try:
        rows = client.table("p1_shifts").select(
            "status, lunch_status, lunch2_status, drink_status"
        ).eq("event_id", event_id).eq("date", date).execute().data or []
    except Exception:
        out["migrated"] = False
        lunch_only = get_lunch_summary(event_id, date)
        out["total_active"] = lunch_only.pop("total_active", 0)
        out["lunch"] = lunch_only
        return out
    for r in rows:
        if (r.get("status") or "") == "absent":
            continue
        out["total_active"] += 1
        for kind, col in DISTRIBUTION_KINDS.items():
            v = (r.get(col) or "pending").lower()
            if v in out[kind]:
                out[kind][v] += 1
    return out


# ============================================================
# 当日運用コード（日替わりワンタイムコード 2026-07-28 追加）
# ============================================================
# 大会当日、TD・給与窓口が「当日運用ページ」（ピット端末・出退勤）に入るための
# 時限コード。管理者が発行し、有効日の翌朝5時(JST)に自動失効する。
# DBにはSHA-256ハッシュのみ保存（発行時に一度だけ平文表示）。
# マイグレ docs/db_migrations/20260728_add_day_codes_and_totp.sql 必須。

def _hash_day_code(code: str) -> str:
    import hashlib
    return hashlib.sha256(("p1daycode:" + (code or "").strip()).encode("utf-8")).hexdigest()


def issue_day_code(valid_date: str, label: str = "", created_by: str = "") -> str:
    """当日運用コードを発行して平文を返す（表示は発行時の一度きり）。

    有効期限 = valid_date の翌日 05:00 JST。
    """
    import secrets as _secrets
    from datetime import datetime as _dt, timedelta as _td
    code = f"{_secrets.randbelow(100000000):08d}"  # 8桁（総当たり耐性・レビュー指摘対応）
    d = _dt.strptime(valid_date, "%Y-%m-%d")
    expires = (d + _td(days=1)).replace(hour=5, minute=0, second=0, tzinfo=_JST)
    get_client().table("p1_day_codes").insert({
        "code_hash": _hash_day_code(code),
        "label": (label or "")[:60],
        "valid_date": valid_date,
        "expires_at": expires.isoformat(),
        "active": 1,
        "created_by": (created_by or "")[:40],
    }).execute()
    log_action("issue_day_code", "auth",
               detail=f"{valid_date} 用の当日運用コードを発行（{label}）",
               performed_by=created_by or "admin")
    return code


def verify_day_code(code: str):
    """当日運用コードを照合。有効なら {valid_date, expires_at, label} を返し、無効なら None。"""
    from datetime import datetime as _dt
    try:
        rows = get_client().table("p1_day_codes").select(
            "id, code_hash, valid_date, expires_at, label, active"
        ).eq("active", 1).eq("code_hash", _hash_day_code(code)).execute().data or []
    except Exception:
        return None
    now = _dt.now(_JST)
    for r in rows:
        try:
            exp = _dt.fromisoformat(str(r["expires_at"]).replace("Z", "+00:00"))
            nbf = _dt.strptime(str(r["valid_date"]), "%Y-%m-%d").replace(tzinfo=_JST)
        except Exception:
            continue
        # 有効日の00:00(JST)より前は使えない（未来日コードの先行使用防止・レビュー指摘対応）
        if nbf <= now < exp:
            return {"id": r["id"], "valid_date": r["valid_date"],
                    "expires_at": r["expires_at"], "label": r.get("label") or ""}
    return None


def is_day_code_active(code_id) -> bool:
    """当日コードが現在も有効（active=1）か。DB障害時は安全側でFalse（レビュー指摘対応）。"""
    try:
        rows = get_client().table("p1_day_codes").select("active").eq(
            "id", code_id).execute().data or []
        return bool(rows and rows[0].get("active"))
    except Exception:
        return False


def list_day_codes(limit: int = 20) -> list:
    """発行済みコードの一覧（ハッシュのみ・平文は返らない）。"""
    try:
        return get_client().table("p1_day_codes").select(
            "id, label, valid_date, expires_at, active, created_by, created_at"
        ).order("created_at", desc=True).limit(limit).execute().data or []
    except Exception:
        return []


def revoke_day_code(code_id: int, performed_by: str = "") -> bool:
    """コードを即時失効させる。"""
    try:
        get_client().table("p1_day_codes").update({"active": 0}).eq("id", code_id).execute()
        log_action("revoke_day_code", "auth", code_id,
                   detail="当日運用コードを失効", performed_by=performed_by or "admin")
        return True
    except Exception:
        return False


# ============================================================
# TOTP 2要素認証（2026-07-28 追加）
# ============================================================
# 管理者ログインに Google Authenticator 等の30秒コードを追加する。
# secret は p1_admin_totp に保存（アプリログインの防御が目的。
# スマホ紛失時は Supabase ダッシュボードで該当行を削除すれば解除できる）。

class TotpLookupError(Exception):
    """TOTP設定の照会に失敗した（＝未設定とは区別する）。

    2026-07-29: 従来は照会失敗を「未設定」と同一視していたため、DB障害時に
    2要素認証が無効化されパスワードだけでログインできた（fail-open）。
    照会できないときは認証を通さない（fail-closed）ため例外で区別する。
    """


def get_totp(account: str):
    """有効なTOTP設定を返す。未設定なら None。照会失敗は TotpLookupError。"""
    try:
        rows = get_client().table("p1_admin_totp").select(
            "account, secret, enabled"
        ).eq("account", (account or "admin")[:40]).eq("enabled", 1).execute().data or []
        return rows[0] if rows else None
    except Exception as e:
        # 「設定が無い」のか「確認できなかった」のかを呼び出し側が区別できるようにする
        raise TotpLookupError(str(e)) from e


def set_totp(account: str, secret: str, enabled: bool, performed_by: str = "") -> bool:
    """TOTP設定を保存（upsert）。"""
    try:
        client = get_client()
        acc = (account or "admin")[:40]
        existing = client.table("p1_admin_totp").select("id").eq("account", acc).execute().data
        payload = {"account": acc, "secret": secret, "enabled": 1 if enabled else 0,
                   "updated_at": _now()}
        if existing:
            client.table("p1_admin_totp").update(payload).eq("account", acc).execute()
        else:
            client.table("p1_admin_totp").insert(payload).execute()
        log_action("set_totp", "auth",
                   detail=f"account={acc} 2要素認証を{'有効化' if enabled else '無効化'}",
                   performed_by=performed_by or acc)
        return True
    except Exception:
        return False


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
    # 2026-07-29 修正: 状態を確認してから更新するまでの間に他端末が支払済みにすると、
    # 支払済みが未承認へ巻き戻る競合があった（ピット端末と給与窓口の同時操作で起こりうる）。
    # 更新条件に status を含め、DB側で原子的に弾く。
    _res = client.table("p1_payments").update({
        "status": "pending", "approved_by": None, "approved_at": None,
    }).eq("id", payment["id"]).neq("status", "paid").execute()
    if not _res.data:
        log_action("freeze_recalc_skipped", "payments", payment["id"],
                   detail=f"{reason}: 直前に支払済みへ変化したため保護", event_id=event_id)
        return False
    log_action("freeze_recalc", "payments", payment["id"],
                detail=f"{reason}: 未承認に戻した", event_id=event_id)
    return True


def mark_absent(shift_id):
    client = get_client()
    row = client.table("p1_shifts").select("event_id, staff_id").eq("id", shift_id).execute().data
    client.table("p1_shifts").update({
        "status": "absent", "actual_start": None, "actual_end": None
    }).eq("id", shift_id).execute()
    # 欠勤はその日の支払いが丸ごと変わるため、計算済みの支払いを未承認に差し戻す
    if row:
        _revert_payment_if_amount_affected(row[0], reason="欠勤記録（要再計算）")


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
    # 2026-07-29 修正: 以前は「既存を削除してから挿入」していたため、削除に成功して
    # 挿入で通信が切れると支払いレコードが丸ごと消えた（会場Wi-Fi断で現実に起こりうる）。
    # 既存があれば更新、無ければ挿入に変更し、データが消える瞬間を無くした。
    # 更新には status 述語を付け、確認から更新までの間に他端末が支払済みにした場合も弾く。
    if existing.data:
        # 2026-08-02: 金額が変わるのに承認・領収書がそのまま残る欠陥を是正。
        # ピット端末の再打刻（多日程スタッフは毎日通る）で
        #   ・誰も承認していない金額が「承認済み」として現金支払いされる
        #   ・旧額の領収書PDFとトークンが有効なまま、違う額の現金が渡る
        # という統制の穴があった。set_payment_adjustment / recompute_payable_for_event は
        # 既に同じ状況で差し戻し・失効を行っており、save_payment だけが漏れていた。
        _old_total = int(existing.data[0].get("total_amount") or 0)
        if int(total_amount or 0) != _old_total:
            # 金額が変わった → 承認をやり直させる（承認情報もクリア）
            payload["status"] = "pending"
            payload["approved_by"] = None
            payload["approved_at"] = None
            # 旧額の領収書は無効化する（再発行が必要）
            if db_schema.has_column("p1_payments", "receipt_received"):
                payload["receipt_received"] = 0
            if db_schema.has_column("p1_payments", "receipt_pdf_path"):
                payload["receipt_pdf_path"] = None
                payload["receipt_token"] = None
                if db_schema.has_column("p1_payments", "receipt_token_expires_at"):
                    payload["receipt_token_expires_at"] = None
            log_action("payment_reverted_by_recalc", "payments", staff_id,
                       f"再計算で金額変更（¥{_old_total:,}→¥{total_amount:,}）のため"
                       "未承認へ差し戻し・領収書を無効化", event_id)
        _res = client.table("p1_payments").update(payload).eq(
            "id", existing.data[0]["id"]).neq("status", "paid").execute()
        if not _res.data:
            # 直前に支払済みへ変わった等で更新されなかった場合は何も壊さず終了
            log_action("calculate_payment_skipped", "payments", staff_id,
                       "支払済みへ変化したため上書きせず", event_id)
            return
    else:
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



# ============================================================
# アプリユーザー（個人アカウント）2026-07-29 追加
# ============================================================
# 従来は secrets/環境変数でしか定義できず、1人追加するのに再デプロイが要った。
# 画面から追加・削除できるようDBに持たせる。パスワードは平文を保存しない。

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """パスワードをpbkdf2-hmac-sha256（ソルト付き）でハッシュ化する。"""
    import hashlib
    import secrets as _sec
    salt = _sec.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt}${digest}"


def list_app_users(include_inactive: bool = True) -> list:
    """アプリユーザー一覧を返す（password_hash は含めない）。"""
    try:
        q = get_client().table("p1_app_users").select(
            "id, username, display_name, role, active, must_change_password, "
            "created_by, created_at, last_login_at"
        )
        if not include_inactive:
            q = q.eq("active", 1)
        return q.order("username").execute().data or []
    except Exception:
        return []


def get_app_users_for_auth() -> dict:
    """認証用に {username: {password_hash, role, must_change}} を返す。

    有効(active=1)なユーザーのみ。DB障害時は AppUserLookupError を送出し、
    「ユーザーが居ない」と混同させない（混同すると認証方式が勝手に切り替わる）。
    """
    try:
        rows = get_client().table("p1_app_users").select(
            "username, password_hash, role, must_change_password"
        ).eq("active", 1).execute().data or []
    except Exception as e:
        raise AppUserLookupError(str(e)) from e
    out = {}
    for r in rows:
        uname = str(r.get("username") or "").strip()
        ph = str(r.get("password_hash") or "")
        if not uname or not ph.startswith("pbkdf2$"):
            continue
        out[uname] = {
            "password_hash": ph,
            "role": str(r.get("role") or "viewer").strip().lower() or "viewer",
            "must_change": bool(r.get("must_change_password")),
        }
    return out


class AppUserLookupError(Exception):
    """アプリユーザーの照会に失敗した（＝0人とは区別する）。"""


def create_app_user(username: str, password: str, role: str = "viewer",
                    display_name: str = "", performed_by: str = "") -> tuple:
    """ユーザーを作成する。Returns: (成功したか, メッセージ)"""
    uname = str(username or "").strip()
    if not uname or not uname.replace("_", "").replace("-", "").isalnum() or not uname.isascii():
        return False, "ユーザーIDは半角英数字（_ - は可）にしてください。"
    if len(str(password or "")) < 10:
        return False, "パスワードは10文字以上にしてください。"
    if role not in ("admin", "viewer"):
        return False, "権限の指定が不正です。"
    try:
        client = get_client()
        if client.table("p1_app_users").select("id").eq("username", uname).execute().data:
            return False, f"ユーザーID「{uname}」は既に使われています。"
        client.table("p1_app_users").insert({
            "username": uname,
            "display_name": str(display_name or "").strip()[:60],
            "password_hash": hash_password(password),
            "role": role,
            "active": 1,
            "must_change_password": 1,   # 初回ログインで本人に変更させる
            "created_by": str(performed_by or "")[:40],
        }).execute()
        log_action("create_app_user", "auth", detail=f"user={uname}, role={role}",
                   performed_by=performed_by or "admin")
        return True, f"ユーザー「{uname}」を作成しました。"
    except Exception as e:
        return False, f"作成に失敗しました: {e}"


def set_app_user_password(username: str, password: str, *, must_change: bool,
                          performed_by: str = "") -> tuple:
    """パスワードを設定する。must_change=True で次回ログイン時の変更を強制する。"""
    uname = str(username or "").strip()
    if len(str(password or "")) < 10:
        return False, "パスワードは10文字以上にしてください。"
    try:
        res = get_client().table("p1_app_users").update({
            "password_hash": hash_password(password),
            "must_change_password": 1 if must_change else 0,
            "updated_at": _now(),
        }).eq("username", uname).execute()
        if not res.data:
            return False, "対象のユーザーが見つかりません。"
        log_action("set_app_user_password", "auth", detail=f"user={uname}",
                   performed_by=performed_by or uname)
        return True, "パスワードを更新しました。"
    except Exception as e:
        return False, f"更新に失敗しました: {e}"


def update_app_user(username: str, *, role: str = None, active: bool = None,
                    display_name: str = None, performed_by: str = "") -> tuple:
    """権限・有効/無効・表示名を更新する。"""
    uname = str(username or "").strip()
    payload = {"updated_at": _now()}
    if role is not None:
        if role not in ("admin", "viewer"):
            return False, "権限の指定が不正です。"
        payload["role"] = role
    if active is not None:
        payload["active"] = 1 if active else 0
    if display_name is not None:
        payload["display_name"] = str(display_name).strip()[:60]
    try:
        res = get_client().table("p1_app_users").update(payload).eq(
            "username", uname).execute()
        if not res.data:
            return False, "対象のユーザーが見つかりません。"
        log_action("update_app_user", "auth",
                   detail=f"user={uname}, {payload}", performed_by=performed_by or "admin")
        return True, "更新しました。"
    except Exception as e:
        return False, f"更新に失敗しました: {e}"


def touch_app_user_login(username: str) -> None:
    """最終ログイン日時を記録する（失敗しても認証は妨げない）。"""
    try:
        get_client().table("p1_app_users").update(
            {"last_login_at": _now()}).eq("username", str(username or "").strip()).execute()
    except Exception:
        pass
