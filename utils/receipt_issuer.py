"""P1 Staff Manager — 領収書発行オーケストレーター

PDF生成 → Supabase Storageへアップ → トークン発行 → DB保存 → URL返却
を一気通貫で行う高レベルAPI。
"""

from __future__ import annotations

from typing import Optional

import db  # type: ignore

from utils import receipt_db
from utils import receipt_storage
from utils import receipt_token
from utils.receipt_v2 import (
    IssuerInfo,
    ReceiptInput,
    build_receipt_no,
    generate_receipt_pdf_v2,
    today_jst_ymd,
)


def _load_event(event_id: int) -> dict:
    row = db.get_client().table("p1_events").select("name").eq("id", event_id).execute().data
    return row[0] if row else {"name": ""}


def _load_staff(staff_id: int) -> dict:
    row = db.get_client().table("p1_staff").select(
        "name_jp, real_name, address, email"
    ).eq("id", staff_id).execute().data
    return row[0] if row else {}


def _load_seal_bytes(seal_url: str) -> Optional[bytes]:
    """電子印影URLから画像bytesを取得（Supabase Storage or 外部URL）"""
    if not seal_url:
        return None
    try:
        import requests
        r = requests.get(seal_url, timeout=10)
        if r.status_code == 200:
            return r.content
    except Exception:
        return None
    return None


def issue_receipt(
    payment_id: int,
    valid_days: int = 7,
    force_regenerate: bool = False,
) -> dict:
    """領収書1件を発行

    Returns:
        {
            "ok": bool,
            "payment_id": int,
            "receipt_no": str,
            "pdf_path": str,
            "token": str,
            "expires_at": str,
            "download_url": str | None,
            "error": str | None,
        }
    """
    client = db.get_client()
    p_row = client.table("p1_payments").select(
        "id, event_id, staff_id, total_amount, receipt_pdf_path, receipt_token"
    ).eq("id", payment_id).execute().data
    if not p_row:
        return {"ok": False, "error": "支払レコードなし", "payment_id": payment_id}
    p = p_row[0]

    # 既に発行済みで force_regenerate=False ならそのまま返す
    if p.get("receipt_pdf_path") and p.get("receipt_token") and not force_regenerate:
        url = receipt_storage.get_signed_url(
            p["receipt_pdf_path"], valid_seconds=valid_days * 24 * 3600
        )
        return {
            "ok": True, "payment_id": payment_id,
            "receipt_no": p.get("receipt_no") or "",
            "pdf_path": p["receipt_pdf_path"],
            "token": p["receipt_token"],
            "expires_at": "",
            "download_url": url,
            "error": None,
        }

    event_id = p["event_id"]
    staff_id = p["staff_id"]
    amount = p["total_amount"]

    # 発行者情報・イベント・スタッフ取得
    issuer_data = receipt_db.get_issuer_settings(event_id)
    event = _load_event(event_id)
    staff = _load_staff(staff_id)

    issue_date = today_jst_ymd()
    receipt_no = build_receipt_no(event_id, staff_id, issue_date)

    # PDF生成
    try:
        pdf_bytes = generate_receipt_pdf_v2(
            receipt=ReceiptInput(
                receipt_no=receipt_no,
                recipient_name=(staff.get("real_name") or staff.get("name_jp") or "スタッフ"),
                recipient_address=staff.get("address") or "",
                recipient_email=staff.get("email") or "",
                amount=int(amount),
                event_name=event.get("name", ""),
                issue_date=issue_date,
                purpose=issuer_data["receipt_purpose"],
            ),
            issuer=IssuerInfo(
                name=issuer_data["issuer_name"],
                address=issuer_data["issuer_address"],
                tel=issuer_data["issuer_tel"],
                invoice_number=(issuer_data["invoice_number"] or None),
                seal_image_bytes=_load_seal_bytes(issuer_data["issuer_seal_url"]),
            ),
            include_stamp_free_note=True,
        )
    except Exception as e:
        return {"ok": False, "error": f"PDF生成失敗: {e}", "payment_id": payment_id}

    # Storageへアップロード
    try:
        pdf_path = receipt_storage.upload_pdf(event_id, receipt_no, pdf_bytes)
    except Exception as e:
        return {"ok": False, "error": f"アップロード失敗: {e}", "payment_id": payment_id}

    # トークン発行＋DB保存
    token = receipt_token.generate_token()
    expires_at = receipt_token.expiry_iso(valid_days=valid_days)
    receipt_db.save_receipt_meta(payment_id, receipt_no, pdf_path, token, expires_at)

    # Signed URL（Storage直接アクセス）と、内部トークンURLの両方を返す
    signed_url = receipt_storage.get_signed_url(pdf_path, valid_seconds=valid_days * 24 * 3600)

    # audit log
    try:
        db.log_action(
            "issue_receipt", "payments", payment_id,
            detail=f"No.{receipt_no} ¥{amount:,}", event_id=event_id,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "payment_id": payment_id,
        "receipt_no": receipt_no,
        "pdf_path": pdf_path,
        "token": token,
        "expires_at": expires_at,
        "download_url": signed_url,
        "error": None,
    }


def issue_receipts_bulk(
    payment_ids: list[int],
    valid_days: int = 7,
    force_regenerate: bool = False,
) -> dict:
    """領収書を一括発行"""
    successes: list[dict] = []
    failures: list[dict] = []
    for pid in payment_ids:
        r = issue_receipt(pid, valid_days=valid_days, force_regenerate=force_regenerate)
        if r.get("ok"):
            successes.append(r)
        else:
            failures.append(r)
    return {
        "total": len(payment_ids),
        "success": len(successes),
        "failure": len(failures),
        "results": successes + failures,
    }
