"""P1 Staff Manager — 領収書関連DB操作

db.py を拡張せず、別モジュールとして追加。
p1_payments / p1_events の新カラムを扱う。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import db  # type: ignore
from utils import db_schema


JST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(JST).isoformat()


# --- カラム存在チェックの薄いラッパ（このモジュール内で頻出するため局所化） ---
def _has_show_tax_breakdown() -> bool:
    return db_schema.has_column("p1_events", "show_tax_breakdown")


def _has_receipt_original_path() -> bool:
    return db_schema.has_column("p1_payments", "receipt_original_path")


# ==========================================================================
# Event: 発行者情報
# ==========================================================================
def get_issuer_settings(event_id: int) -> dict:
    """イベントの発行者情報を取得（未設定はデフォルト埋め）

    Note:
        show_tax_breakdown カラムはマイグレ未実行なら存在しない。
        その場合は False 固定で返す（後方互換）。
    """
    client = db.get_client()
    cols = [
        "issuer_name", "issuer_address", "issuer_tel", "invoice_number",
        "issuer_seal_url", "receipt_purpose",
    ]
    if _has_show_tax_breakdown():
        cols.append("show_tax_breakdown")
    res = client.table("p1_events").select(", ".join(cols)).eq(
        "id", event_id).execute()
    row = res.data[0] if res.data else {}
    return {
        "issuer_name": row.get("issuer_name") or "株式会社パシフィック",
        "issuer_address": row.get("issuer_address") or "",
        "issuer_tel": row.get("issuer_tel") or "",
        "invoice_number": row.get("invoice_number") or "",
        "issuer_seal_url": row.get("issuer_seal_url") or "",
        "receipt_purpose": row.get("receipt_purpose") or "ポーカー大会運営業務委託費として",
        "show_tax_breakdown": bool(row.get("show_tax_breakdown") or 0),
    }


def save_issuer_settings(event_id: int, **fields) -> None:
    """発行者情報を更新（部分更新OK）

    Note:
        show_tax_breakdown カラムが未作成の場合は、そのキーだけ黙って除外する。
    """
    allowed = {
        "issuer_name", "issuer_address", "issuer_tel",
        "invoice_number", "issuer_seal_url", "receipt_purpose",
        "show_tax_breakdown",
    }
    payload = {k: v for k, v in fields.items() if k in allowed}
    if "show_tax_breakdown" in payload:
        if _has_show_tax_breakdown():
            # DB側は INT なので 0/1 に正規化
            payload["show_tax_breakdown"] = 1 if payload["show_tax_breakdown"] else 0
        else:
            # カラム未作成なら更新から除外（他の設定は反映する）
            payload.pop("show_tax_breakdown", None)
    if not payload:
        return
    db.get_client().table("p1_events").update(payload).eq("id", event_id).execute()


# ==========================================================================
# Payment: 領収書メタ
# ==========================================================================
def save_receipt_meta(
    payment_id: int,
    receipt_no: str,
    pdf_path: str,
    token: str,
    expires_at_iso: str,
    pdf_path_copy: Optional[str] = None,
    pdf_path_original: Optional[str] = None,
) -> None:
    """PDFアップロード後、payments行にメタ情報を保存

    Args:
        pdf_path: 後方互換用（従来のメインPDFパス。通常は copy と同じ）
        pdf_path_copy: 受領者配布用（控え）PDFパス（明示的に渡す場合）
        pdf_path_original: 発行者保管用（原本）PDFパス
    """
    payload = {
        "receipt_no": receipt_no,
        # 後方互換: receipt_pdf_path には「控え」を格納する運用
        "receipt_pdf_path": pdf_path_copy or pdf_path,
        "receipt_token": token,
        "receipt_token_expires_at": expires_at_iso,
        "receipt_generated_at": _now_iso(),
    }
    # receipt_original_path カラムが存在する場合のみ書き込む（マイグレ前は無視）
    if pdf_path_original is not None and _has_receipt_original_path():
        payload["receipt_original_path"] = pdf_path_original
    db.get_client().table("p1_payments").update(payload).eq("id", payment_id).execute()


def mark_receipt_downloaded(payment_id: int) -> None:
    """DL時にカウントと日時更新"""
    client = db.get_client()
    row = client.table("p1_payments").select(
        "receipt_download_count"
    ).eq("id", payment_id).execute().data
    cur = (row[0].get("receipt_download_count") or 0) if row else 0
    client.table("p1_payments").update({
        "receipt_download_count": cur + 1,
        "receipt_downloaded_at": _now_iso(),
    }).eq("id", payment_id).execute()


def find_payment_by_token(token: str) -> Optional[dict]:
    """トークンから支払レコードを検索（検証用）

    receipt_original_path が未作成なら SELECT リストから外す。
    """
    if not token:
        return None
    client = db.get_client()
    cols = [
        "id", "event_id", "staff_id", "total_amount", "receipt_no",
        "receipt_pdf_path",
        "receipt_token_expires_at", "receipt_download_count",
    ]
    if _has_receipt_original_path():
        cols.insert(6, "receipt_original_path")  # receipt_pdf_path の後ろへ
    res = client.table("p1_payments").select(", ".join(cols)).eq(
        "receipt_token", token).execute()
    return res.data[0] if res.data else None


def get_payments_needing_receipt(event_id: int,
                                   status_filter: str = "all") -> list[dict]:
    """領収書発行対象の支払一覧を取得

    Args:
        status_filter:
            "all" = 全支払
            "unissued" = 未発行のみ (receipt_pdf_pathがnull)
            "approved_or_paid" = 承認済み/支払済みのみ
    """
    client = db.get_client()
    payment_cols = [
        "id", "event_id", "staff_id", "total_amount", "status",
        "receipt_no", "receipt_pdf_path", "receipt_token",
        "receipt_token_expires_at", "receipt_generated_at",
        "receipt_download_count",
    ]
    if _has_receipt_original_path():
        payment_cols.insert(7, "receipt_original_path")
    select_expr = ", ".join(payment_cols) + (
        ", p1_staff(name_jp, name_en, no, role, real_name, address, email)"
    )
    q = client.table("p1_payments").select(select_expr).eq("event_id", event_id)
    rows = q.execute().data
    # staff結合のlist/dict両対応
    out = []
    for r in rows:
        staff = r.pop("p1_staff", None)
        if isinstance(staff, list):
            staff = staff[0] if staff else {}
        if not isinstance(staff, dict):
            staff = {}
        r.update({
            "name_jp": staff.get("name_jp", ""),
            "name_en": staff.get("name_en", ""),
            "no": staff.get("no", 0),
            "role": staff.get("role", "Dealer"),
            "real_name": staff.get("real_name") or "",
            "address": staff.get("address") or "",
            "email": staff.get("email") or "",
        })
        out.append(r)

    if status_filter == "unissued":
        out = [r for r in out if not r.get("receipt_pdf_path")]
    elif status_filter == "approved_or_paid":
        out = [r for r in out if r.get("status") in ("approved", "paid")]
    return sorted(out, key=lambda x: x.get("no", 0))
