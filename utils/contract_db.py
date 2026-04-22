"""P1 Staff Manager — 契約書DB操作"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import db  # type: ignore
from utils import db_schema


JST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(JST).isoformat()


def _has_is_provisional() -> bool:
    """p1_contract_templates.is_provisional カラムの存在判定"""
    return db_schema.has_column("p1_contract_templates", "is_provisional")


# ==========================================================================
# Templates
# ==========================================================================
def list_templates(active_only: bool = True) -> list[dict]:
    q = db.get_client().table("p1_contract_templates").select("*").order("id")
    if active_only:
        q = q.eq("is_active", 1)
    return q.execute().data


def get_template(template_id: int) -> Optional[dict]:
    r = db.get_client().table("p1_contract_templates").select(
        "*").eq("id", template_id).execute().data
    return r[0] if r else None


def create_template(name: str, version: str, doc_type: str,
                      body_markdown: str,
                      is_provisional: int = 1) -> int:
    """テンプレを新規登録する。

    Args:
        is_provisional: 1=仮版（経理レビュー前・PDFに透かし）、0=正規版。
            既定は仮版。手動アップロードされた正規版のみ 0 を渡す想定。

    Note:
        is_provisional カラムが未作成のDBなら、そのキーは送らない（後方互換）。
    """
    payload = {
        "name": name,
        "version": version,
        "doc_type": doc_type,
        "body_markdown": body_markdown,
        "is_active": 1,
    }
    if _has_is_provisional():
        payload["is_provisional"] = int(is_provisional)
    r = db.get_client().table("p1_contract_templates").insert(payload).execute()
    return r.data[0]["id"] if r.data else 0


def update_template(template_id: int, **fields) -> None:
    allowed = {"name", "version", "doc_type", "body_markdown",
                "is_active", "is_provisional"}
    payload = {k: v for k, v in fields.items() if k in allowed}
    if not payload:
        return
    if "is_provisional" in payload:
        if _has_is_provisional():
            payload["is_provisional"] = int(payload["is_provisional"])
        else:
            # カラム未作成なら黙って除外（他の更新は通す）
            payload.pop("is_provisional", None)
        if not payload:
            # 残ったフィールドが無ければ何もしない
            return
    payload["updated_at"] = _now_iso()
    db.get_client().table("p1_contract_templates").update(payload).eq(
        "id", template_id).execute()


def deactivate_template(template_id: int) -> None:
    update_template(template_id, is_active=0)


# ==========================================================================
# Contracts
# ==========================================================================
def create_contract(
    template_id: int,
    staff_id: int,
    contract_no: str,
    variables: dict,
    event_id: Optional[int] = None,
    rendered_body_md: Optional[str] = None,
    template_version: Optional[str] = None,
    template_name_snapshot: Optional[str] = None,
) -> int:
    """契約発行時のスナップショットを保持した行を作成

    Args:
        rendered_body_md: 発行時点のレンダリング済み本文。
            署名時はこれを使うことで、テンプレ改変の影響を受けない（CR-1対策）。
        template_version: 発行時点のテンプレバージョン
        template_name_snapshot: 発行時点のテンプレ名
    """
    payload = {
        "template_id": template_id,
        "staff_id": staff_id,
        "event_id": event_id,
        "contract_no": contract_no,
        "status": "draft",
        "variables_json": json.dumps(variables, ensure_ascii=False),
    }
    if rendered_body_md is not None:
        payload["rendered_body_md"] = rendered_body_md
    if template_version is not None:
        payload["template_version"] = template_version
    if template_name_snapshot is not None:
        payload["template_name_snapshot"] = template_name_snapshot
    r = db.get_client().table("p1_contracts").insert(payload).execute()
    return r.data[0]["id"] if r.data else 0


def save_unsigned_meta(contract_id: int, pdf_path: str, token: str,
                         expires_at_iso: str) -> None:
    db.get_client().table("p1_contracts").update({
        "unsigned_pdf_path": pdf_path,
        "signing_token": token,
        "signing_token_expires_at": expires_at_iso,
        "status": "sent",
        "sent_at": _now_iso(),
        "updated_at": _now_iso(),
    }).eq("id", contract_id).execute()


def find_contract_by_token(token: str) -> Optional[dict]:
    if not token:
        return None
    r = db.get_client().table("p1_contracts").select("*").eq(
        "signing_token", token).execute().data
    return r[0] if r else None


def mark_viewed(contract_id: int) -> None:
    client = db.get_client()
    row = client.table("p1_contracts").select(
        "view_count, status, viewed_at"
    ).eq("id", contract_id).execute().data
    if not row:
        return
    cur = row[0]
    update = {
        "view_count": (cur.get("view_count") or 0) + 1,
        "updated_at": _now_iso(),
    }
    if not cur.get("viewed_at"):
        update["viewed_at"] = _now_iso()
    if cur.get("status") == "sent":
        update["status"] = "viewed"
    client.table("p1_contracts").update(update).eq("id", contract_id).execute()


def save_signed(contract_id: int, signed_pdf_path: str,
                  signature_image_path: str, content_hash: str,
                  signer_ip: str = "", signer_ua: str = "") -> None:
    db.get_client().table("p1_contracts").update({
        "signed_pdf_path": signed_pdf_path,
        "signature_image_path": signature_image_path,
        "content_hash": content_hash,
        "signer_ip": signer_ip[:50],
        "signer_user_agent": (signer_ua or "")[:500],
        "signed_at": _now_iso(),
        "status": "signed",
        "updated_at": _now_iso(),
    }).eq("id", contract_id).execute()


def revoke_contract(contract_id: int, reason: str) -> None:
    db.get_client().table("p1_contracts").update({
        "status": "revoked",
        "revoked_at": _now_iso(),
        "revoke_reason": reason[:500],
        "updated_at": _now_iso(),
    }).eq("id", contract_id).execute()


def list_contracts(status_filter: Optional[str] = None,
                    staff_id: Optional[int] = None,
                    event_id: Optional[int] = None) -> list[dict]:
    """契約一覧（スタッフ情報含む）"""
    client = db.get_client()
    q = client.table("p1_contracts").select(
        "*, p1_staff(name_jp, name_en, no, role, real_name, email), "
        "p1_contract_templates(name, version, doc_type)"
    )
    if status_filter:
        q = q.eq("status", status_filter)
    if staff_id:
        q = q.eq("staff_id", staff_id)
    if event_id:
        q = q.eq("event_id", event_id)
    rows = q.order("created_at", desc=True).execute().data
    # 結合結果のフラット化
    out = []
    for r in rows:
        staff = r.pop("p1_staff", None)
        if isinstance(staff, list):
            staff = staff[0] if staff else {}
        if not isinstance(staff, dict):
            staff = {}
        tpl = r.pop("p1_contract_templates", None)
        if isinstance(tpl, list):
            tpl = tpl[0] if tpl else {}
        if not isinstance(tpl, dict):
            tpl = {}
        r.update({
            "staff_name_jp": staff.get("name_jp", ""),
            "staff_no": staff.get("no", 0),
            "staff_real_name": staff.get("real_name") or "",
            "staff_email": staff.get("email") or "",
            "staff_role": staff.get("role") or "",
            "template_name": tpl.get("name", ""),
            "template_version": tpl.get("version", ""),
            "doc_type": tpl.get("doc_type") or "",
        })
        out.append(r)
    return out
