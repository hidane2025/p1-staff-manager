"""当日運用コード・TOTP・個人アカウント（db.py から2026-08-06に機械分割・挙動不変）"""
import os
import re
import unicodedata
import streamlit as st
from datetime import datetime, timezone, timedelta
from typing import Optional
try:
    from supabase import create_client
except ImportError:
    create_client = None

from dbx import core
from dbx.core import _JST


# ============================================================
# 当日運用コード（日替わりワンタイムコード 2026-07-28 追加）
# ============================================================
# 大会当日、TD・給与窓口が「当日運用ページ」（ピット端末・出退勤）に入るための
# 時限コード。管理者が発行し、有効日の翌朝5時(JST)に自動失効する。
# DBにはSHA-256ハッシュのみ保存（発行時に一度だけ平文表示）。
# マイグレ docs/db_migrations/20260728_add_day_codes_and_totp.sql 必須。

def _hash_day_code(code: str) -> str:
    import hashlib
    return hashlib.sha256(("p1daycode:" + (code or "").strip()).encode("utf-8")).hexdigest()


def issue_day_code(valid_date: str, label: str = "", created_by: str = "") -> str:
    """当日運用コードを発行して平文を返す（表示は発行時の一度きり）。

    有効期限 = valid_date の翌日 05:00 JST。
    """
    import secrets as _secrets
    from datetime import datetime as _dt, timedelta as _td
    code = f"{_secrets.randbelow(100000000):08d}"  # 8桁（総当たり耐性・レビュー指摘対応）
    d = _dt.strptime(valid_date, "%Y-%m-%d")
    expires = (d + _td(days=1)).replace(hour=5, minute=0, second=0, tzinfo=_JST)
    core.get_client().table("p1_day_codes").insert({
        "code_hash": _hash_day_code(code),
        "label": (label or "")[:60],
        "valid_date": valid_date,
        "expires_at": expires.isoformat(),
        "active": 1,
        "created_by": (created_by or "")[:40],
    }).execute()
    core.log_action("issue_day_code", "auth",
               detail=f"{valid_date} 用の当日運用コードを発行（{label}）",
               performed_by=created_by or "admin")
    return code


def verify_day_code(code: str):
    """当日運用コードを照合。有効なら {valid_date, expires_at, label} を返し、無効なら None。"""
    from datetime import datetime as _dt
    try:
        rows = core.get_client().table("p1_day_codes").select(
            "id, code_hash, valid_date, expires_at, label, active"
        ).eq("active", 1).eq("code_hash", _hash_day_code(code)).execute().data or []
    except Exception:
        return None
    now = _dt.now(_JST)
    for r in rows:
        try:
            exp = _dt.fromisoformat(str(r["expires_at"]).replace("Z", "+00:00"))
            nbf = _dt.strptime(str(r["valid_date"]), "%Y-%m-%d").replace(tzinfo=_JST)
        except Exception:
            continue
        # 有効日の00:00(JST)より前は使えない（未来日コードの先行使用防止・レビュー指摘対応）
        if nbf <= now < exp:
            return {"id": r["id"], "valid_date": r["valid_date"],
                    "expires_at": r["expires_at"], "label": r.get("label") or ""}
    return None


def is_day_code_active(code_id) -> bool:
    """当日コードが現在も有効（active=1）か。DB障害時は安全側でFalse（レビュー指摘対応）。"""
    try:
        rows = core.get_client().table("p1_day_codes").select("active").eq(
            "id", code_id).execute().data or []
        return bool(rows and rows[0].get("active"))
    except Exception:
        return False


def list_day_codes(limit: int = 20) -> list:
    """発行済みコードの一覧（ハッシュのみ・平文は返らない）。"""
    try:
        return core.get_client().table("p1_day_codes").select(
            "id, label, valid_date, expires_at, active, created_by, created_at"
        ).order("created_at", desc=True).limit(limit).execute().data or []
    except Exception:
        return []


def revoke_day_code(code_id: int, performed_by: str = "") -> bool:
    """コードを即時失効させる。"""
    try:
        core.get_client().table("p1_day_codes").update({"active": 0}).eq("id", code_id).execute()
        core.log_action("revoke_day_code", "auth", code_id,
                   detail="当日運用コードを失効", performed_by=performed_by or "admin")
        return True
    except Exception:
        return False


# ============================================================
# TOTP 2要素認証（2026-07-28 追加）
# ============================================================
# 管理者ログインに Google Authenticator 等の30秒コードを追加する。
# secret は p1_admin_totp に保存（アプリログインの防御が目的。
# スマホ紛失時は Supabase ダッシュボードで該当行を削除すれば解除できる）。

class TotpLookupError(Exception):
    """TOTP設定の照会に失敗した（＝未設定とは区別する）。

    2026-07-29: 従来は照会失敗を「未設定」と同一視していたため、DB障害時に
    2要素認証が無効化されパスワードだけでログインできた（fail-open）。
    照会できないときは認証を通さない（fail-closed）ため例外で区別する。
    """


def get_totp(account: str):
    """有効なTOTP設定を返す。未設定なら None。照会失敗は TotpLookupError。"""
    try:
        rows = core.get_client().table("p1_admin_totp").select(
            "account, secret, enabled"
        ).eq("account", (account or "admin")[:40]).eq("enabled", 1).execute().data or []
        return rows[0] if rows else None
    except Exception as e:
        # 「設定が無い」のか「確認できなかった」のかを呼び出し側が区別できるようにする
        raise TotpLookupError(str(e)) from e


def set_totp(account: str, secret: str, enabled: bool, performed_by: str = "") -> bool:
    """TOTP設定を保存（upsert）。"""
    try:
        client = core.get_client()
        acc = (account or "admin")[:40]
        existing = client.table("p1_admin_totp").select("id").eq("account", acc).execute().data
        payload = {"account": acc, "secret": secret, "enabled": 1 if enabled else 0,
                   "updated_at": core._now()}
        if existing:
            client.table("p1_admin_totp").update(payload).eq("account", acc).execute()
        else:
            client.table("p1_admin_totp").insert(payload).execute()
        core.log_action("set_totp", "auth",
                   detail=f"account={acc} 2要素認証を{'有効化' if enabled else '無効化'}",
                   performed_by=performed_by or acc)
        return True
    except Exception:
        return False



# ============================================================
# アプリユーザー（個人アカウント）2026-07-29 追加
# ============================================================
# 従来は secrets/環境変数でしか定義できず、1人追加するのに再デプロイが要った。
# 画面から追加・削除できるようDBに持たせる。パスワードは平文を保存しない。

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """パスワードをpbkdf2-hmac-sha256（ソルト付き）でハッシュ化する。"""
    import hashlib
    import secrets as _sec
    salt = _sec.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt}${digest}"


def list_app_users(include_inactive: bool = True) -> list:
    """アプリユーザー一覧を返す（password_hash は含めない）。"""
    try:
        q = core.get_client().table("p1_app_users").select(
            "id, username, display_name, role, active, must_change_password, "
            "created_by, created_at, last_login_at"
        )
        if not include_inactive:
            q = q.eq("active", 1)
        return q.order("username").execute().data or []
    except Exception:
        return []


def get_app_users_for_auth() -> dict:
    """認証用に {username: {password_hash, role, must_change}} を返す。

    有効(active=1)なユーザーのみ。DB障害時は AppUserLookupError を送出し、
    「ユーザーが居ない」と混同させない（混同すると認証方式が勝手に切り替わる）。
    """
    try:
        rows = core.get_client().table("p1_app_users").select(
            "username, password_hash, role, must_change_password"
        ).eq("active", 1).execute().data or []
    except Exception as e:
        raise AppUserLookupError(str(e)) from e
    out = {}
    for r in rows:
        uname = str(r.get("username") or "").strip()
        ph = str(r.get("password_hash") or "")
        if not uname or not ph.startswith("pbkdf2$"):
            continue
        out[uname] = {
            "password_hash": ph,
            "role": str(r.get("role") or "viewer").strip().lower() or "viewer",
            "must_change": bool(r.get("must_change_password")),
        }
    return out


class AppUserLookupError(Exception):
    """アプリユーザーの照会に失敗した（＝0人とは区別する）。"""


def create_app_user(username: str, password: str, role: str = "viewer",
                    display_name: str = "", performed_by: str = "") -> tuple:
    """ユーザーを作成する。Returns: (成功したか, メッセージ)"""
    uname = str(username or "").strip()
    if not uname or not uname.replace("_", "").replace("-", "").isalnum() or not uname.isascii():
        return False, "ユーザーIDは半角英数字（_ - は可）にしてください。"
    if len(str(password or "")) < 10:
        return False, "パスワードは10文字以上にしてください。"
    if role not in ("admin", "viewer"):
        return False, "権限の指定が不正です。"
    try:
        client = core.get_client()
        if client.table("p1_app_users").select("id").eq("username", uname).execute().data:
            return False, f"ユーザーID「{uname}」は既に使われています。"
        client.table("p1_app_users").insert({
            "username": uname,
            "display_name": str(display_name or "").strip()[:60],
            "password_hash": hash_password(password),
            "role": role,
            "active": 1,
            "must_change_password": 1,   # 初回ログインで本人に変更させる
            "created_by": str(performed_by or "")[:40],
        }).execute()
        core.log_action("create_app_user", "auth", detail=f"user={uname}, role={role}",
                   performed_by=performed_by or "admin")
        return True, f"ユーザー「{uname}」を作成しました。"
    except Exception as e:
        return False, f"作成に失敗しました: {e}"


def set_app_user_password(username: str, password: str, *, must_change: bool,
                          performed_by: str = "") -> tuple:
    """パスワードを設定する。must_change=True で次回ログイン時の変更を強制する。"""
    uname = str(username or "").strip()
    if len(str(password or "")) < 10:
        return False, "パスワードは10文字以上にしてください。"
    try:
        res = core.get_client().table("p1_app_users").update({
            "password_hash": hash_password(password),
            "must_change_password": 1 if must_change else 0,
            "updated_at": core._now(),
        }).eq("username", uname).execute()
        if not res.data:
            return False, "対象のユーザーが見つかりません。"
        core.log_action("set_app_user_password", "auth", detail=f"user={uname}",
                   performed_by=performed_by or uname)
        return True, "パスワードを更新しました。"
    except Exception as e:
        return False, f"更新に失敗しました: {e}"


def update_app_user(username: str, *, role: str = None, active: bool = None,
                    display_name: str = None, performed_by: str = "") -> tuple:
    """権限・有効/無効・表示名を更新する。"""
    uname = str(username or "").strip()
    payload = {"updated_at": core._now()}
    if role is not None:
        if role not in ("admin", "viewer"):
            return False, "権限の指定が不正です。"
        payload["role"] = role
    if active is not None:
        payload["active"] = 1 if active else 0
    if display_name is not None:
        payload["display_name"] = str(display_name).strip()[:60]
    try:
        res = core.get_client().table("p1_app_users").update(payload).eq(
            "username", uname).execute()
        if not res.data:
            return False, "対象のユーザーが見つかりません。"
        core.log_action("update_app_user", "auth",
                   detail=f"user={uname}, {payload}", performed_by=performed_by or "admin")
        return True, "更新しました。"
    except Exception as e:
        return False, f"更新に失敗しました: {e}"


def touch_app_user_login(username: str) -> None:
    """最終ログイン日時を記録する（失敗しても認証は妨げない）。"""
    try:
        core.get_client().table("p1_app_users").update(
            {"last_login_at": core._now()}).eq("username", str(username or "").strip()).execute()
    except Exception:
        pass
