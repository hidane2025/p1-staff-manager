"""P1 Staff Manager — 領収書発行オーケストレーター

PDF生成 → Supabase Storageへアップ → トークン発行 → DB保存 → URL返却
を一気通貫で行う高レベルAPI。

2026-04-21 拡張:
    発行者保管用（原本）とスタッフ配布用（控え）の2バージョンを同時生成し、
    それぞれ別パスでストレージへUPする。消費税額の内訳表示にも対応。
"""

from __future__ import annotations

from typing import Optional

import db  # type: ignore

from utils import db_schema
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


def _build_receipt_input(
    receipt_no: str,
    staff: dict,
    amount: int,
    event_name: str,
    issue_date: str,
    purpose: str,
) -> ReceiptInput:
    """PDF生成用の入力データを組み立て（DRY）"""
    return ReceiptInput(
        receipt_no=receipt_no,
        recipient_name=(staff.get("real_name") or staff.get("name_jp") or "スタッフ"),
        recipient_address=staff.get("address") or "",
        recipient_email=staff.get("email") or "",
        amount=int(amount),
        event_name=event_name,
        issue_date=issue_date,
        purpose=purpose,
    )


def issue_receipt(
    payment_id: int,
    valid_days: int = 7,
    force_regenerate: bool = False,
) -> dict:
    """領収書1件を発行（原本＋控えの2バージョン）

    Returns:
        {
            "ok": bool,
            "payment_id": int,
            "receipt_no": str,
            "pdf_path": str,            # 後方互換: 控えのパス
            "copy_path": str,           # 控え（スタッフ配布用）
            "original_path": str,       # 原本（発行者保管用）
            "token": str,
            "expires_at": str,
            "download_url": str | None,
            "error": str | None,
        }
    """
    client = db.get_client()
    # receipt_original_path が未作成のDBでも動くよう、SELECTリストを動的に構築
    p_cols = [
        "id", "event_id", "staff_id", "total_amount",
        "receipt_pdf_path", "receipt_token", "receipt_no",
    ]
    if db_schema.has_column("p1_payments", "receipt_original_path"):
        p_cols.insert(5, "receipt_original_path")
    p_row = client.table("p1_payments").select(", ".join(p_cols)).eq(
        "id", payment_id).execute().data
    if not p_row:
        return {"ok": False, "error": "支払レコードなし", "payment_id": payment_id}
    p = p_row[0]

    # 既に発行済みで force_regenerate=False ならそのまま返す
    if p.get("receipt_pdf_path") and p.get("receipt_token") and not force_regenerate:
        url = receipt_storage.get_signed_url(
            p["receipt_pdf_path"], valid_seconds=valid_days * 24 * 3600
        )
        return {
            "ok": True,
            "payment_id": payment_id,
            "receipt_no": p.get("receipt_no") or "",
            "pdf_path": p["receipt_pdf_path"],
            "copy_path": p.get("receipt_pdf_path") or "",
            "original_path": p.get("receipt_original_path") or "",
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

    issuer_info = IssuerInfo(
        name=issuer_data["issuer_name"],
        address=issuer_data["issuer_address"],
        tel=issuer_data["issuer_tel"],
        invoice_number=(issuer_data["invoice_number"] or None),
        seal_image_bytes=_load_seal_bytes(issuer_data["issuer_seal_url"]),
    )
    receipt_input = _build_receipt_input(
        receipt_no=receipt_no,
        staff=staff,
        amount=int(amount),
        event_name=event.get("name", ""),
        issue_date=issue_date,
        purpose=issuer_data["receipt_purpose"],
    )
    tax_flag = bool(issuer_data.get("show_tax_breakdown"))

    # PDF生成: 原本 + 控え
    try:
        pdf_original = generate_receipt_pdf_v2(
            receipt=receipt_input,
            issuer=issuer_info,
            include_stamp_free_note=True,
            document_type="original",
            tax_breakdown=tax_flag,
        )
        pdf_copy = generate_receipt_pdf_v2(
            receipt=receipt_input,
            issuer=issuer_info,
            include_stamp_free_note=True,
            document_type="copy",
            tax_breakdown=tax_flag,
        )
    except Exception as e:
        return {"ok": False, "error": f"PDF生成失敗: {e}", "payment_id": payment_id}

    # Storageへアップロード（原本・控え）
    try:
        original_path = receipt_storage.upload_pdf_at(
            receipt_storage.original_pdf_path(event_id, receipt_no),
            pdf_original,
        )
        copy_path = receipt_storage.upload_pdf_at(
            receipt_storage.copy_pdf_path(event_id, receipt_no),
            pdf_copy,
        )
    except Exception as e:
        return {"ok": False, "error": f"アップロード失敗: {e}", "payment_id": payment_id}

    # トークン発行＋DB保存（receipt_pdf_path は後方互換で控えパスを入れる）
    token = receipt_token.generate_token()
    expires_at = receipt_token.expiry_iso(valid_days=valid_days)
    receipt_db.save_receipt_meta(
        payment_id=payment_id,
        receipt_no=receipt_no,
        pdf_path=copy_path,  # 後方互換
        token=token,
        expires_at_iso=expires_at,
        pdf_path_copy=copy_path,
        pdf_path_original=original_path,
    )

    # Signed URL（スタッフ配布用の控え）
    signed_url = receipt_storage.get_signed_url(
        copy_path, valid_seconds=valid_days * 24 * 3600
    )

    # audit log
    try:
        db.log_action(
            "issue_receipt", "payments", payment_id,
            detail=f"No.{receipt_no} ¥{amount:,} (orig+copy)",
            event_id=event_id,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "payment_id": payment_id,
        "receipt_no": receipt_no,
        "pdf_path": copy_path,        # 後方互換
        "copy_path": copy_path,
        "original_path": original_path,
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
