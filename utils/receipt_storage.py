"""P1 Staff Manager — 領収書PDFのSupabase Storage連携

バケット: 'receipts' (非公開)
ファイル構造: receipts/event_{event_id}/R-YYYYMMDD-E{eventId}-S{staffId}.pdf
"""

from __future__ import annotations

from typing import Optional

import db  # type: ignore


BUCKET = "receipts"


def _storage():
    return db.get_client().storage


def storage_path(event_id: int, receipt_no: str) -> str:
    """ストレージ上のファイルパスを決定論的に生成"""
    safe = receipt_no.replace("/", "_").replace("..", "")
    return f"event_{event_id}/{safe}.pdf"


def upload_pdf(event_id: int, receipt_no: str, pdf_bytes: bytes) -> str:
    """PDFをアップロードしてパスを返す。既存あれば上書き。"""
    path = storage_path(event_id, receipt_no)
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
