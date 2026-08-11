"""スタッフ台帳と名寄せ（db.py から2026-08-06に機械分割・挙動不変）"""
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


# === Staff CRUD ===

def create_staff(no, name_jp, name_en="", role="Dealer", contact="", notes="",
                 real_name="", address="", email="",
                 employment_type="contractor", custom_hourly_rate=None,
                 nearest_station="", prefecture=None, region=None):
    from utils.region import address_to_region
    # 重複チェック: NO.が指定されていて既存の場合はエラーを投げる
    if no and no > 0:
        existing = core.get_client().table("p1_staff").select("id, name_jp").eq("no", no).execute()
        if existing.data:
            raise ValueError(f"NO.{no} は既に {existing.data[0]['name_jp']} で登録されています")
    # 住所から都道府県・地域を自動判定（明示指定が無ければ）
    if address and (not prefecture or not region):
        auto_pref, auto_region = address_to_region(address)
        prefecture = prefecture or auto_pref
        region = region or auto_region
    r = core.get_client().table("p1_staff").insert({
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
    q = core.get_client().table("p1_staff").select("*").eq("is_active", 1).order("role").order("no")
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
    r = core.get_client().table("p1_staff").select("*").eq("id", staff_id).execute()
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
    kwargs["updated_at"] = core._now()
    core.get_client().table("p1_staff").update(kwargs).eq("id", staff_id).execute()


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
    client = core.get_client()
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
                payload["updated_at"] = core._now()
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
    client = core.get_client()
    has_no = False
    if no not in (None, ""):
        try:
            has_no = int(no) > 0
        except (ValueError, TypeError):
            has_no = False
    if has_no:
        r = client.table("p1_staff").select("id").eq("no", no).execute()
        if r.data:
            return r.data[0]["id"]
        # NO.があって未登録なら「新しい人」。ここで名前照合に落とすと、
        # 同姓同名の別人（例: 2026-08 大阪の NO.79 と NO.510 の「Aoi」）が
        # 1人に統合され、片方の勤務が上書きで消える。NO.は一意キーなので、
        # 明示されている以上それを尊重して新規作成する。
        return create_staff(no, name_jp, name_en, role)
    nk = _norm_key(name_jp)
    if nk:
        r = client.table("p1_staff").select("id, name_jp").execute()
        for s in (r.data or []):
            if _norm_key(s.get("name_jp")) == nk:
                return s["id"]
    return create_staff(no, name_jp, name_en, role)
