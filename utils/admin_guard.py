"""P1 Staff Manager — 管理者ページのガード（v3.7 セキュリティ対策）

【役割】
Streamlit Cloud の Viewer 認証は「招待された人なら誰でもアプリに入れる」設定。
ただし PII（本名・住所・支払額・契約書PDF）を扱う管理ページは追加で
管理者パスワードを要求する。

【設定方法】
Streamlit Cloud → アプリ設定 → Secrets で以下を追加:
    ADMIN_PASSWORD = "強いパスワードを入れる"

ローカル開発時は .streamlit/secrets.toml に同じキーを設定。
.streamlit/secrets.toml は .gitignore 済みなのでコミットされない。

【パスワード未設定時】
ADMIN_PASSWORD が空文字列の場合、警告だけ出してアプリは通常通り動作する。
これはローカル開発時の利便性のため。本番環境では必ず設定すること。

【ログ】
ログイン成功・失敗は p1_audit_log テーブルに記録される。
    - admin_login: 成功
    - admin_login_failed: 失敗（PWの長さだけ記録、内容は記録しない）
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import streamlit as st


_JST = timezone(timedelta(hours=9))
_SESSION_KEY = "p1_admin_authenticated"
_LOGIN_AT_KEY = "p1_admin_login_at"
_LOGIN_AS_KEY = "p1_admin_login_as"


def _get_admin_password() -> str:
    """st.secrets > 環境変数 の順で探す。"""
    try:
        v = st.secrets.get("ADMIN_PASSWORD")
        if v:
            return str(v)
    except Exception:
        pass
    import os
    return os.environ.get("ADMIN_PASSWORD", "")


def is_admin() -> bool:
    """現在のセッションが管理者として認証済みか"""
    return bool(st.session_state.get(_SESSION_KEY))


def admin_login_at() -> str:
    return str(st.session_state.get(_LOGIN_AT_KEY) or "")


def require_admin(*, page_name: str = "") -> None:
    """管理者専用ページの**先頭**で呼ぶ。未認証なら認証画面を出して st.stop()。

    Args:
        page_name: ログ用のページ識別子（例 "領収書発行"）
    """
    if is_admin():
        return

    expected = _get_admin_password()
    if not expected:
        # 未設定時はフォールバックで通す（ローカル開発の利便性）
        st.warning(
            "⚠️ **ADMIN_PASSWORD が未設定です。** "
            "本番環境では Streamlit Cloud の Secrets に必ず設定してください。"
            "（ローカル開発時はこの警告を無視してOK）",
            icon="🔓",
        )
        return

    # 認証画面
    st.markdown("## 🔒 管理者認証が必要です")
    st.caption(
        f"このページ（{page_name or '管理者専用'}）はスタッフの本名・住所・支払額・"
        f"契約書PDFを扱います。閲覧・操作には管理者パスワードが必要です。"
    )

    with st.form("__admin_login_form__"):
        operator = st.text_input(
            "オペレーター名（任意）", value="",
            placeholder="例: 中野 / 伊藤",
            help="操作ログに記録される名前。誰が触ったかの追跡用。",
        )
        pw = st.text_input("管理者パスワード", type="password",
                            placeholder="Streamlit Cloud Secrets の ADMIN_PASSWORD")
        submitted = st.form_submit_button("🔓 ログイン", type="primary")

    if submitted:
        # 比較は constant-time に近づける（短絡評価を避ける）
        ok = (
            isinstance(pw, str)
            and isinstance(expected, str)
            and len(pw) == len(expected)
            and _consteq(pw, expected)
        )
        # 比較結果に関わらず最低限の遅延（タイミング攻撃の弱体化）
        import time
        time.sleep(0.15)

        if ok:
            st.session_state[_SESSION_KEY] = True
            st.session_state[_LOGIN_AT_KEY] = datetime.now(_JST).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            st.session_state[_LOGIN_AS_KEY] = (operator or "anonymous_admin")[:30]
            _log_safe(
                "admin_login", "auth",
                detail=f"page={page_name}, by={operator[:30] if operator else 'anon'}",
                performed_by=operator[:30] or "admin",
            )
            st.rerun()
        else:
            _log_safe(
                "admin_login_failed", "auth",
                detail=f"page={page_name}, pw_len={len(pw or '')}, by={operator[:30] if operator else 'anon'}",
                performed_by=operator[:30] or "anonymous",
            )
            st.error("❌ パスワードが違います")

    st.stop()


def admin_logout_button() -> None:
    """サイドバーや画面上部に置く管理者ログアウトボタン。
    認証済みのときだけ表示。"""
    if is_admin():
        operator = st.session_state.get(_LOGIN_AS_KEY) or "—"
        login_at = admin_login_at()
        with st.sidebar:
            st.caption(f"🔐 管理者: {operator}　({login_at})")
            if st.button("🔓 管理者ログアウト", use_container_width=True):
                _log_safe("admin_logout", "auth",
                          detail=f"by={operator}", performed_by=operator)
                st.session_state[_SESSION_KEY] = False
                st.session_state[_LOGIN_AT_KEY] = ""
                st.session_state[_LOGIN_AS_KEY] = ""
                st.rerun()


def operator_name() -> str:
    """現在のセッションの管理者名を返す（未認証なら "anonymous"）"""
    return str(st.session_state.get(_LOGIN_AS_KEY) or "anonymous")


# ============================================================
# Internal
# ============================================================
def _consteq(a: str, b: str) -> bool:
    """定数時間比較（タイミング攻撃の対策）。長さは事前に揃えている前提。"""
    import hmac
    return hmac.compare_digest(a, b)


def _log_safe(action: str, target_type: str, *, detail: str = "",
              performed_by: str = "system") -> None:
    """ログ書き込み失敗時はサイレント（DB接続エラーで認証画面が壊れないように）"""
    try:
        import db  # type: ignore
        db.log_action(action, target_type, detail=detail, performed_by=performed_by)
    except Exception:
        pass
