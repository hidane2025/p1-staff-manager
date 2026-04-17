"""P1 Staff Manager — 領収書DLトークン生成・検証"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone


JST = timezone(timedelta(hours=9))


def generate_token() -> str:
    """URLセーフなランダムトークン（32bytes=256bit）

    衝突確率は実用上ゼロ。UUID4より強い。
    """
    return secrets.token_urlsafe(32)


def expiry_iso(valid_days: int = 7) -> str:
    """有効期限をJST基準のISO文字列で返す"""
    exp = datetime.now(JST) + timedelta(days=valid_days)
    return exp.isoformat()


def is_expired(expires_at_iso: str | None) -> bool:
    """期限切れ判定。None/空なら期限切れ扱い（安全側）"""
    if not expires_at_iso:
        return True
    try:
        exp = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) > exp.astimezone(timezone.utc)
