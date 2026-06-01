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
    # Codex P2 R5 レビュー対応 (2026-05-25):
    #   issuer_name は p1_events 上で共有されており、領収書（payer_name）と
    #   契約書（{{issuer_name}}）の両方で使われる。よって本関数は raw 値を返し、
    #   領収書向けのフォールバック（レガシー値→新PRT名）は呼び出し側
    #   （resolve_payer_name + receipt_issuer.py）で局所適用する。
    #   この設計により、92ページでの保存が契約書側の表示を破壊しない。
    return {
        "issuer_name": row.get("issuer_name") or "",
        "issuer_address": row.get("issuer_address") or "",
        "issuer_tel": row.get("issuer_tel") or "",
        "invoice_number": row.get("invoice_number") or "",
        "issuer_seal_url": row.get("issuer_seal_url") or "",
        "receipt_purpose": row.get("receipt_purpose") or "ポーカー大会運営業務委託費として",
        "show_tax_breakdown": bool(row.get("show_tax_breakdown") or 0),
    }


# 2026-05-25: 旧マイグレーションで p1_events.issuer_name に書き込まれる
# 既定値。これらが入っているレコードは「未設定」と同等とみなし、
# 領収書では新しい PRT 名へフォールバックする。
_LEGACY_ISSUER_NAMES_FOR_RECEIPT: frozenset[str] = frozenset({
    "株式会社パシフィック",
    "株式会社 パシフィック",
})

_DEFAULT_PAYER_NAME = "株式会社 PACIFIC RACING TEAM"


def resolve_payer_name(stored_issuer_name: str) -> str:
    """領収書の宛名として使う payer_name にフォールバックを適用。

    Args:
        stored_issuer_name: get_issuer_settings() で取得した issuer_name の raw 値。

    Returns:
        ・空文字 or レガシー値（旧仕様の "株式会社パシフィック" 系）の場合は
          新しい PRT 名称（_DEFAULT_PAYER_NAME）にマップ。
        ・それ以外（管理者が明示的に上書きした値）はそのまま返す。

    Note:
        この関数は領収書発行パス限定。契約書生成（utils.contract_issuer）は
        raw 値をそのまま使うので、本関数を介さない。
    """
    s = (stored_issuer_name or "").strip()
    if not s or s in _LEGACY_ISSUER_NAMES_FOR_RECEIPT:
        return _DEFAULT_PAYER_NAME
    return s


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


def revoke_receipt_token(payment_id: int, performed_by: str = "system",
                          event_id: Optional[int] = None) -> None:
    """領収書DLトークンを即時失効させる（C-1）。

    有効期限(receipt_token_expires_at)を過去日時に上書きするだけ。
    これにより receipt_token.is_expired() が True を返し、DLページは
    「期限切れ」表示になってPDFを返さなくなる。トークン値自体は残すので、
    監査上「どのトークンが失効されたか」を find_payment_by_token で追える。
    再発行（強制再生成）すれば新しい期限で復活できる（破壊的でない）。

    用途: トークン付きURLの誤送信・転送・流出時に、有効期限切れを待たず
    第三者アクセスを止める。契約側の contract_db.revoke_contract と対をなす。

    Args:
        performed_by: 失効を実行した操作者（監査証跡。呼び出し側で operator_name() を渡す）。
        event_id: 対象イベント（監査ログをイベントで絞り込めるようにする）。
    """
    past_iso = (datetime.now(JST) - timedelta(days=1)).isoformat()
    db.get_client().table("p1_payments").update({
        "receipt_token_expires_at": past_iso,
    }).eq("id", payment_id).execute()
    db.log_action(
        "revoke_receipt_token", "payments", payment_id,
        detail="領収書DLトークンを失効（有効期限を過去に設定）",
        event_id=event_id, performed_by=performed_by,
    )


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
    # A-6: DLページの表示額を確定額に揃えるため payable_amount も取得
    if db_schema.has_column("p1_payments", "payable_amount"):
        cols.append("payable_amount")
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
    # A-6: 発行一覧の金額も確定額(payable_amount)で表示するため取得
    if db_schema.has_column("p1_payments", "payable_amount"):
        payment_cols.append("payable_amount")
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
