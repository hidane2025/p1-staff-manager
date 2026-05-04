"""P1 Staff Manager — 契約書発行・署名オーケストレーター"""

from __future__ import annotations

from html import escape as _html_escape
from typing import Optional

import db  # type: ignore


def _safe(s: Optional[str]) -> str:
    """テンプレ変数の HTML エスケープ。
    本名・住所・メール等のスタッフ入力値が rendered_body_md に埋め込まれるため、
    Markdown経由のst.markdown表示やPDF再描画時のXSS/構造破壊を防ぐ。
    Markdown 特有の制御文字（# * _ など）は意図的にエスケープしない（書式保持）。
    """
    if s is None:
        return ""
    return _html_escape(str(s), quote=True)

from utils import contract_db, contract_storage
from utils import receipt_token   # secrets.token_urlsafe ベースで共通
from utils import receipt_db as rdb  # issuer情報の取得に利用
from utils.contract_pdf import (
    ContractVariables,
    build_contract_no,
    compute_content_hash,
    generate_contract_pdf,
    render_template,
    today_jst_ymd,
)


def _load_staff(staff_id: int) -> dict:
    r = db.get_client().table("p1_staff").select(
        "name_jp, real_name, address, email, role"
    ).eq("id", staff_id).execute().data
    return r[0] if r else {}


def _load_event(event_id: Optional[int]) -> dict:
    if not event_id:
        return {}
    r = db.get_client().table("p1_events").select(
        "name, issuer_name, issuer_address"
    ).eq("id", event_id).execute().data
    return r[0] if r else {}


def issue_contract(
    template_id: int,
    staff_id: int,
    event_id: Optional[int] = None,
    valid_days: int = 14,
) -> dict:
    """契約書を発行（未署名PDF生成→Storage→トークン発行→DB保存）

    Returns:
        {ok, contract_id, contract_no, token, signing_url, expires_at, error}
    """
    tpl = contract_db.get_template(template_id)
    if not tpl:
        return {"ok": False, "error": "テンプレートが見つかりません"}

    staff = _load_staff(staff_id)
    if not staff:
        return {"ok": False, "error": "スタッフが見つかりません"}

    event = _load_event(event_id)
    # 発行者情報（大会に紐づく場合は大会から、それ以外はデフォルト）
    issuer_name = event.get("issuer_name") or "株式会社パシフィック"
    issuer_address = event.get("issuer_address") or ""

    issue_date = today_jst_ymd()
    contract_no = build_contract_no(template_id, staff_id, issue_date)

    # P1#7 (2026-05-04): スタッフ自己申告データを HTML エスケープ
    # → 本名に <script> 等が混じっていた場合の XSS を防ぐ
    variables = ContractVariables(
        staff_name=_safe(staff.get("real_name") or staff.get("name_jp")),
        staff_address=_safe(staff.get("address")),
        staff_email=_safe(staff.get("email")),
        role=_safe(staff.get("role")),
        event_name=_safe(event.get("name") or "大会全般"),
        issuer_name=_safe(issuer_name),
        issuer_address=_safe(issuer_address),
        issue_date=issue_date,
    )
    rendered = render_template(tpl["body_markdown"], variables)
    is_provisional = bool(tpl.get("is_provisional", 1))

    # PDF生成（未署名）
    pdf_bytes = generate_contract_pdf(
        rendered_body=rendered,
        contract_no=contract_no,
        issuer_name=issuer_name,
        is_provisional=is_provisional,
    )

    # DB行作成（rendered_body_mdもスナップショットとして記録）
    # → 署名時のテンプレ改変に影響されない（Ultra Review CR-1対策）
    contract_id = contract_db.create_contract(
        template_id, staff_id, contract_no,
        variables=variables.to_dict(),
        event_id=event_id,
        rendered_body_md=rendered,
        template_version=tpl.get("version"),
        template_name_snapshot=tpl.get("name"),
    )
    if not contract_id:
        return {"ok": False, "error": "DB書き込み失敗"}

    # Storage upload
    try:
        path = contract_storage.upload_bytes(
            contract_storage.unsigned_pdf_path(contract_no), pdf_bytes)
    except Exception as e:
        return {"ok": False, "error": f"アップロード失敗: {e}",
                "contract_id": contract_id}

    # トークン発行
    token = receipt_token.generate_token()
    expires_at = receipt_token.expiry_iso(valid_days=valid_days)
    contract_db.save_unsigned_meta(contract_id, path, token, expires_at)

    try:
        provisional_note = " [仮版で発行]" if is_provisional else ""
        db.log_action(
            "issue_contract", "contracts", contract_id,
            detail=f"{contract_no} → {staff.get('name_jp')}{provisional_note}",
            event_id=event_id,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "contract_id": contract_id,
        "contract_no": contract_no,
        "token": token,
        "expires_at": expires_at,
        "pdf_path": path,
        "is_provisional": is_provisional,
        "error": None,
    }


def issue_contracts_bulk(template_id: int, staff_ids: list[int],
                            event_id: Optional[int] = None,
                            valid_days: int = 14) -> dict:
    success, failure = [], []
    for sid in staff_ids:
        r = issue_contract(template_id, sid, event_id=event_id,
                             valid_days=valid_days)
        (success if r.get("ok") else failure).append(r)
    return {
        "total": len(staff_ids), "success": len(success),
        "failure": len(failure), "results": success + failure,
    }


def apply_signature(contract_id: int, signature_png: bytes,
                      signer_ip: str = "", signer_ua: str = "") -> dict:
    """署名画像を受け取り、署名済PDFを生成してStorageに保存

    ※ Ultra Review CR-1対策:
    発行時にスナップショット保存したrendered_body_mdを優先使用する。
    テンプレが発行後に編集されても、署名対象の内容は固定される。
    """
    from datetime import datetime, timedelta, timezone
    JST = timezone(timedelta(hours=9))

    client = db.get_client()
    row = client.table("p1_contracts").select(
        "id, contract_no, template_id, variables_json, event_id, status, rendered_body_md"
    ).eq("id", contract_id).execute().data
    if not row:
        return {"ok": False, "error": "契約が見つかりません"}
    c = row[0]

    if c["status"] == "signed":
        return {"ok": False, "error": "すでに署名済みです"}
    if c["status"] == "revoked":
        return {"ok": False, "error": "この契約は無効化されています"}

    import json as _json
    variables_dict = _json.loads(c["variables_json"] or "{}")

    # CR-1対策: 発行時スナップショットを最優先
    # 旧契約（rendered_body_md未記録）のみ、互換のためテンプレから再生成
    rendered = c.get("rendered_body_md")
    tpl = contract_db.get_template(c["template_id"]) if c.get("template_id") else None
    if not rendered:
        if not tpl:
            return {"ok": False, "error": "テンプレートが見つかりません"}
        rendered = tpl["body_markdown"]
        for k, v in variables_dict.items():
            rendered = rendered.replace(f"{{{{{k}}}}}", v or "")

    # 仮版フラグは発行時のテンプレ状態を参照。
    # テンプレが削除済みのレガシー契約は False（安全側：透かしなし）で扱う。
    is_provisional = bool(tpl.get("is_provisional", 0)) if tpl else False

    # 署名日時
    signed_at_iso = datetime.now(JST).isoformat()
    content_hash = compute_content_hash(rendered, signed_at_iso, c["contract_no"])

    # 署名画像をStorageに保存
    try:
        sig_path = contract_storage.upload_bytes(
            contract_storage.signature_image_path(c["contract_no"]),
            signature_png, content_type="image/png",
        )
    except Exception as e:
        return {"ok": False, "error": f"署名画像保存失敗: {e}"}

    # 署名済PDF生成
    try:
        signed_pdf = generate_contract_pdf(
            rendered_body=rendered,
            contract_no=c["contract_no"],
            issuer_name=variables_dict.get("issuer_name") or "",
            signature_image_bytes=signature_png,
            signed_at_iso=signed_at_iso,
            is_provisional=is_provisional,
        )
        signed_path = contract_storage.upload_bytes(
            contract_storage.signed_pdf_path(c["contract_no"]), signed_pdf,
        )
    except Exception as e:
        return {"ok": False, "error": f"署名済PDF生成失敗: {e}"}

    contract_db.save_signed(
        contract_id, signed_path, sig_path, content_hash,
        signer_ip=signer_ip, signer_ua=signer_ua,
    )

    try:
        db.log_action(
            "sign_contract", "contracts", contract_id,
            detail=f"{c['contract_no']} 署名完了 hash={content_hash[:16]}",
            event_id=c.get("event_id"),
        )
    except Exception:
        pass

    return {
        "ok": True,
        "contract_id": contract_id,
        "signed_pdf_path": signed_path,
        "content_hash": content_hash,
        "signed_at": signed_at_iso,
    }
