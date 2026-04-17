"""P1 Staff Manager — 契約書のSupabase Storage連携"""

from __future__ import annotations

from typing import Optional

import db  # type: ignore


BUCKET = "contracts"


def _storage():
    return db.get_client().storage


def unsigned_pdf_path(contract_no: str) -> str:
    safe = contract_no.replace("/", "_").replace("..", "")
    return f"unsigned/{safe}.pdf"


def signed_pdf_path(contract_no: str) -> str:
    safe = contract_no.replace("/", "_").replace("..", "")
    return f"signed/{safe}.pdf"


def signature_image_path(contract_no: str) -> str:
    safe = contract_no.replace("/", "_").replace("..", "")
    return f"signatures/{safe}.png"


def upload_bytes(path: str, content: bytes,
                   content_type: str = "application/pdf") -> str:
    try:
        _storage().from_(BUCKET).remove([path])
    except Exception:
        pass
    _storage().from_(BUCKET).upload(
        path=path,
        file=content,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return path


def download_bytes(path: str) -> Optional[bytes]:
    try:
        res = _storage().from_(BUCKET).download(path)
        if isinstance(res, (bytes, bytearray)):
            return bytes(res)
    except Exception:
        pass
    return None


def get_signed_url(path: str, valid_seconds: int = 14 * 24 * 3600) -> Optional[str]:
    try:
        res = _storage().from_(BUCKET).create_signed_url(path, valid_seconds)
        return res.get("signedURL") or res.get("signedUrl")
    except Exception:
        return None
