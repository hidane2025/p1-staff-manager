"""P1 Staff Manager — 領収書PDFのSupabase Storage連携

バケット: 'receipts' (非公開)
ファイル構造:
    旧（後方互換で残存）:
        receipts/event_{event_id}/R-YYYYMMDD-E{eventId}-S{staffId}.pdf
    新（2026-04-21 以降の2バージョン生成対応）:
        receipts/event_{event_id}/original/R-YYYYMMDD-E{eventId}-S{staffId}.pdf
        receipts/event_{event_id}/copy/R-YYYYMMDD-E{eventId}-S{staffId}.pdf
"""

from __future__ import annotations

from typing import Optional

import db  # type: ignore


BUCKET = "receipts"


def _storage():
    return db.get_client().storage


def _safe_receipt_no(receipt_no: str) -> str:
    """ストレージキーに使える形に正規化（軽い防御）"""
    return receipt_no.replace("/", "_").replace("..", "")


def storage_path(event_id: int, receipt_no: str) -> str:
    """ストレージ上のファイルパスを決定論的に生成（旧仕様・後方互換用）"""
    return f"event_{event_id}/{_safe_receipt_no(receipt_no)}.pdf"


def original_pdf_path(event_id: int, receipt_no: str) -> str:
    """発行者保管用（原本）PDFのストレージパス"""
    return f"event_{event_id}/original/{_safe_receipt_no(receipt_no)}.pdf"


def copy_pdf_path(event_id: int, receipt_no: str) -> str:
    """受領者配布用（控え）PDFのストレージパス"""
    return f"event_{event_id}/copy/{_safe_receipt_no(receipt_no)}.pdf"


def upload_pdf(event_id: int, receipt_no: str, pdf_bytes: bytes) -> str:
    """PDFをアップロードしてパスを返す。既存あれば上書き。（旧API・後方互換）"""
    path = storage_path(event_id, receipt_no)
    return _upload_at_path(path, pdf_bytes)


def upload_pdf_at(storage_path_str: str, pdf_bytes: bytes) -> str:
    """指定パスにアップロード。既存あれば上書き。"""
    return _upload_at_path(storage_path_str, pdf_bytes)


def _upload_at_path(path: str, pdf_bytes: bytes) -> str:
    """内部ヘルパー: 指定パスへupsertアップロード"""
    try:
        # 既存あれば削除（upsert相当の手動実装）
        _storage().from_(BUCKET).remove([path])
    except Exception:
        pass
    _storage().from_(BUCKET).upload(
        path=path,
        file=pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )
    return path


def get_signed_url(storage_path_str: str, valid_seconds: int = 7 * 24 * 3600) -> Optional[str]:
    """Signed URLを発行（デフォルト7日有効）"""
    try:
        res = _storage().from_(BUCKET).create_signed_url(storage_path_str, valid_seconds)
        # supabase-py v2: {"signedURL": "..."} / v1: {"signedUrl": "..."}
        return res.get("signedURL") or res.get("signedUrl")
    except Exception as e:
        print(f"[receipt_storage] signed_url失敗: {e}")
        return None


def download_pdf(storage_path_str: str) -> Optional[bytes]:
    """ストレージからPDFを直接取得（サーバー内配布用）"""
    try:
        res = _storage().from_(BUCKET).download(storage_path_str)
        if isinstance(res, (bytes, bytearray)):
            return bytes(res)
        return None
    except Exception as e:
        print(f"[receipt_storage] download失敗: {e}")
        return None


def delete_pdf(storage_path_str: str) -> bool:
    try:
        _storage().from_(BUCKET).remove([storage_path_str])
        return True
    except Exception:
        return False
