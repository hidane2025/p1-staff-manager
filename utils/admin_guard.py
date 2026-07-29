"""P1 Staff Manager — 管理者ページのガード（v3.15 多ユーザー認証）

【役割】
PII（本名・住所・支払額・契約書PDF）を扱う管理ページの手前で認証を要求する。

【認証モードと解決順（後方互換）】
1. **多ユーザー（推奨）**: Streamlit Secrets に `[auth.users]` があれば
   「ユーザーID＋パスワード＋ロール」で認証する。ロールでアクセス権を制御。
2. **単一パスワード（旧）**: `[auth.users]` が無く `ADMIN_PASSWORD` があれば、
   従来の単一パスワード方式で動く（既存運用を壊さない）。
3. **パスワードレス（dev）**: どちらも無ければ警告だけ出して通す（ローカル開発）。

【設定方法（多ユーザー）】
Streamlit Cloud → アプリ設定 → Secrets（またはローカル .streamlit/secrets.toml）:
    [auth.users.nakano]
    password_hash = "pbkdf2$200000$<salt_hex>$<hash_hex>"   # scripts/make_app_user.py で生成
    role = "admin"
    [auth.users.window1]
    password_hash = "..."
    role = "viewer"

- ロール: "admin"=全操作 / "viewer"=閲覧のみ（各ページが roles= で許可ロールを指定）。
- パスワードはハッシュのみ保存（平文は保存しない）。ハッシュは pbkdf2-hmac-sha256（ソルト付き）。
- secrets はサーバ側のみ・リポジトリに出ない（DBに置かないので anon キー露出の影響を受けない）。

【監査】
ログイン成功/失敗は p1_audit_log に記録（パスワード内容は記録しない）。
認証後は operator_name() がユーザーIDを返すため、承認者・支払実行者の記録が実名になる。
"""

from __future__ import annotations

import os as _os

import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from typing import Optional

import streamlit as st


_JST = timezone(timedelta(hours=9))
_SESSION_KEY = "p1_admin_authenticated"
_LOGIN_AT_KEY = "p1_admin_login_at"
_LOGIN_AS_KEY = "p1_admin_login_as"
_ROLE_KEY = "p1_admin_role"
_DAY_EXPIRES_KEY = "p1_day_code_expires"
_DAY_CODE_ID_KEY = "p1_day_code_id"
_DAY_FAILS_KEY = "p1_day_code_fails"
_LAST_SEEN_KEY = "p1_admin_last_seen"

# 2026-07-29: 管理セッションに期限を設ける。
# 共有端末を開いたまま離席・紛失した場合に、無期限で操作できてしまうのを防ぐ。
_SESSION_ABSOLUTE_HOURS = 12   # ログインから12時間で強制ログアウト（大会1日の運用を想定）
_SESSION_IDLE_MINUTES = 60     # 60分操作がなければログアウト
_TOTP_PENDING_KEY = "p1_totp_pending"   # {"user":..., "role":...} パスワード通過後のTOTP待ち

_PBKDF2_ALGO = "sha256"
_PBKDF2_ITER = 200_000


# ============================================================
# ユーザーストア（Streamlit Secrets）
# ============================================================

def _env_auth_users() -> dict:
    """環境変数 AUTH_USERS（JSON）から個人アカウント定義を読む。

    2026-07-29 追加の理由:
        個人アカウント方式は従来 secrets.toml（ファイル）からしか読めなかったが、
        本番はコンテナで動きファイルを置かないため使えなかった。結果として
        全員が同じパスワードを共有し、監査ログの「誰が」が名前の自己申告に
        依存していた。環境変数から読めるようにして、1人1アカウントに移行する。

    形式:
        AUTH_USERS={"nakano":{"password_hash":"pbkdf2$...","role":"admin"},
                    "ito":{"password_hash":"pbkdf2$...","role":"admin"}}
    """
    raw = (_os.environ.get("AUTH_USERS") or "").strip()
    if not raw:
        return {}
    try:
        import json as _json
        return dict(_json.loads(raw))
    except Exception:
        return {}


def _auth_users_configured() -> bool:
    """Secrets に [auth.users] セクションが存在するか（中身の妥当性は問わない）。

    存在＝多ユーザー認証を「意図している」とみなす。たとえ全entryが不正でも、
    パスワードレス(dev)に落として無認証アクセスを許さない（fail closed）ための判定。
    """
    try:
        try:
            import db as _db
            if _db.get_app_users_for_auth():
                return True
        except Exception:
            pass
        if _env_auth_users():
            return True
        auth = st.secrets.get("auth")
        if not auth:
            return False
        return auth.get("users") is not None
    except Exception:
        return False


def _load_app_users() -> dict:
    """Secrets の [auth.users] を {username: {password_hash, role}} として返す。

    **有効な（pbkdf2 形式の password_hash を持つ）entry のみ**を返す。
    未設定・読取不可・有効ユーザー無しなら空 dict。
    ※ [auth.users] が存在するのに空 dict の場合は、require_admin 側で
      パスワードレスに落とさず fail closed する（_auth_users_configured で判定）。
    """
    try:
        # 2026-07-29: 画面から追加できるDBのユーザーを最優先にする。
        # （環境変数・secretsは移行期の後方互換として残す）
        try:
            import db as _db
            _dbu = _db.get_app_users_for_auth()
            if _dbu:
                return {k: {"password_hash": v["password_hash"], "role": v["role"]}
                        for k, v in _dbu.items()}
        except Exception:
            # DB障害時は環境変数・secretsへフォールバックする。
            # ここで空を返すと単一パスワードモードに落ちて認証が緩むため、
            # 下の経路で必ず何らかの定義を探す。
            pass
        users = _env_auth_users()
        if not users:
            auth = st.secrets.get("auth")
            users = auth.get("users") if auth else None
        if not users:
            return {}
        out = {}
        for uname, meta in dict(users).items():
            m = dict(meta) if hasattr(meta, "keys") else {}
            ph = str(m.get("password_hash") or "")
            # password_hash が無い/壊れた entry は無視する（形式全体を検証）。
            # 切れたコピペ等で "pbkdf2$..." 風だが不正な値も弾く。全entryが弾かれて
            # users が空になっても、require_admin 側が _auth_users_configured で
            # fail closed する（パスワードレスに落とさない）。
            if not _valid_pbkdf2(ph):
                continue
            # role は認可境界。省略・誤記時は最小権限(viewer)にフォールバックする
            # （誤って admin を与えない）。未知ロールはどのゲートにも一致せず自然に締まる。
            # 先に strip/lower してから空判定 → 空白のみの role も viewer に倒す
            # （" " が "" として保存され、後段で admin に化けるのを防ぐ）。
            role = str(m.get("role") or "").strip().lower() or "viewer"
            out[str(uname).strip()] = {"password_hash": ph, "role": role}
        return out
    except Exception:
        return {}


def hash_password(password: str, *, iterations: int = _PBKDF2_ITER,
                  salt: Optional[bytes] = None) -> str:
    """pbkdf2-hmac-sha256 でパスワードをハッシュ化し `pbkdf2$iter$salt$hash` 形式で返す。

    CLI（scripts/make_app_user.py）と検証で共通利用する。
    """
    import os
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode("utf-8"), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${dk.hex()}"


def _valid_pbkdf2(stored: str) -> bool:
    """`pbkdf2$iter$salt$hash` の形式が完全に妥当か（4要素・iter整数・salt/hashがhex非空）。

    "pbkdf2$" で始まるだけの不完全な値（切れたコピペ等）を弾くために、採用前に使う。
    """
    try:
        scheme, iter_s, salt_hex, hash_hex = stored.split("$", 3)
        if scheme != "pbkdf2":
            return False
        if int(iter_s) <= 0:
            return False
        if not salt_hex or not hash_hex:
            return False
        bytes.fromhex(salt_hex)
        bytes.fromhex(hash_hex)
        return True
    except Exception:
        return False


def _verify_password(password: str, stored: str) -> bool:
    """`pbkdf2$iter$salt$hash` 形式のハッシュと平文パスワードを定数時間で照合。"""
    if not _valid_pbkdf2(stored):
        return False
    try:
        _scheme, iter_s, salt_hex, hash_hex = stored.split("$", 3)
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _authenticate(username: str, password: str) -> Optional[str]:
    """ユーザーID＋パスワードを照合し、成功ならロール文字列を返す（失敗は None）。"""
    users = _load_app_users()
    u = users.get((username or "").strip())
    # ユーザー不在でもダミー検証して存在有無のタイミング差を減らす
    stored = u.get("password_hash") if u else "pbkdf2$200000$00$00"
    ok = _verify_password(password or "", stored)
    if u and ok and u.get("password_hash"):
        # _load_app_users で role は正規化済み（空なら viewer）。
        # 念のためここでも最小権限フォールバック（絶対に admin に昇格させない）。
        return u.get("role") or "viewer"
    return None


# ============================================================
# 旧: 単一パスワード（後方互換）
# ============================================================
def _get_admin_password() -> str:
    """st.secrets > 環境変数 の順で単一管理者パスワードを探す。"""
    try:
        v = st.secrets.get("ADMIN_PASSWORD")
        if v:
            return str(v)
    except Exception:
        pass
    import os
    return os.environ.get("ADMIN_PASSWORD", "")


# ============================================================
# 公開API
# ============================================================
def is_auth_enabled() -> bool:
    """認証が実際に機能しているか（多ユーザー or 単一パスワードが設定済みか）。

    False のときはパスワードレス運用（dev）で、操作者必須ゲートはかけない。
    [auth.users] が存在すれば（不正設定でも）認証は「有効」とみなす（fail closed 側）。
    """
    return _auth_users_configured() or bool(_get_admin_password())


def is_admin() -> bool:
    """現在のセッションが認証済みか（ロールは current_role で確認）。"""
    return bool(st.session_state.get(_SESSION_KEY))


def current_role() -> str:
    """現在のセッションのロール。パスワードレス(dev)は 'admin' 扱い。"""
    if not is_auth_enabled():
        return "admin"
    return str(st.session_state.get(_ROLE_KEY) or "")


def admin_login_at() -> str:
    return str(st.session_state.get(_LOGIN_AT_KEY) or "")


def current_user() -> str:
    """ログイン中のユーザーID（多ユーザーモード時）。未ログインや共有PW運用では空。"""
    try:
        return str(st.session_state.get(_LOGIN_AS_KEY) or "").strip()
    except Exception:
        return ""


def operator_name() -> str:
    """現在のセッションの操作者名（多ユーザーならユーザーID）。未認証は 'anonymous'。"""
    return str(st.session_state.get(_LOGIN_AS_KEY) or "anonymous")


def _role_allowed(role: str, roles) -> bool:
    if not roles:
        return True
    return (role or "") in set(roles)




def _session_expired() -> bool:
    """絶対期限（ログインから12時間）と無操作期限（60分）を判定する。"""
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.now(_JST)
    try:
        login_at = st.session_state.get(_LOGIN_AT_KEY)
        if login_at:
            t = _dt.strptime(str(login_at), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_JST)
            if now - t > _td(hours=_SESSION_ABSOLUTE_HOURS):
                return True
    except Exception:
        pass
    try:
        last = st.session_state.get(_LAST_SEEN_KEY)
        if last:
            t = _dt.fromisoformat(str(last))
            if now - t > _td(minutes=_SESSION_IDLE_MINUTES):
                return True
    except Exception:
        pass
    return False


def _touch_session() -> None:
    """最終操作時刻を更新する（無操作期限の判定用）。"""
    from datetime import datetime as _dt
    st.session_state[_LAST_SEEN_KEY] = _dt.now(_JST).isoformat()


def _clear_session() -> None:
    """セッション情報を消す（期限切れ・ログアウト共通）。"""
    for _k in (_SESSION_KEY, _LOGIN_AT_KEY, _LOGIN_AS_KEY, _ROLE_KEY,
               _DAY_EXPIRES_KEY, _DAY_CODE_ID_KEY, _LAST_SEEN_KEY, _TOTP_PENDING_KEY):
        st.session_state.pop(_k, None)



_PWCHANGE_PENDING_KEY = "p1_pwchange_pending"


def _must_change_password(username: str) -> bool:
    """初期パスワードのままかどうか（DBに登録が無い場合は False）。"""
    try:
        import db as _db
        info = _db.get_app_users_for_auth().get(str(username or "").strip())
        return bool(info and info.get("must_change"))
    except Exception:
        return False


def _render_password_change(pending: dict) -> None:
    """初回ログイン時のパスワード変更画面。ここを通らないと中に入れない。"""
    user = str(pending.get("user") or "")
    st.markdown("## 🔑 パスワードの変更が必要です")
    st.caption(
        f"「{user}」さん、はじめまして。管理者が設定した初期パスワードのままです。\n\n"
        "ご自身だけが知るパスワードに変更してください。"
        "変更後は、管理者を含め誰もあなたのパスワードを知らない状態になります。"
    )
    with st.form("__pwchange_form__"):
        pw1 = st.text_input("新しいパスワード（10文字以上）", type="password")
        pw2 = st.text_input("確認のためもう一度", type="password")
        ok = st.form_submit_button("🔑 変更してログイン", type="primary")
    if ok:
        if len(pw1 or "") < 10:
            st.error("10文字以上にしてください。")
        elif pw1 != pw2:
            st.error("2つの入力が一致しません。")
        else:
            try:
                import db as _db
                done, msg = _db.set_app_user_password(
                    user, pw1, must_change=False, performed_by=user)
            except Exception as e:
                done, msg = False, str(e)
            if done:
                st.session_state.pop(_PWCHANGE_PENDING_KEY, None)
                _finish_or_totp(username=user, role=str(pending.get("role") or "viewer"),
                                account=user or "admin",
                                page_name=str(pending.get("page_name") or ""))
            else:
                st.error(f"変更できませんでした: {msg}")
    st.stop()


def _monitor_login_failure(kind: str, detail: str = "") -> None:
    """認証失敗を監視モジュールへ通知する（失敗しても認証処理は続行）。"""
    try:
        from utils import monitoring
        monitoring.record_login_failure(kind, detail)
    except Exception:
        pass


def require_admin(*, page_name: str = "", roles=("admin",),
                  allow_day_code: bool = False) -> None:
    """管理者専用ページの**先頭**で呼ぶ。未認証/権限不足なら認証画面を出して st.stop()。

    Args:
        page_name: ログ用のページ識別子（例 "領収書発行"）
        roles: 入室を許可するロールの集合（既定 admin のみ）。
               閲覧者にも開くページは roles=("admin","viewer") を渡す。
        allow_day_code: True の場合「当日運用コード」でも入室可（ピット端末・出退勤用。
               2026-07-28 追加。コードは管理者が発行・翌朝5時JSTに自動失効）。
    """
    # 既に認証済み → ロールを確認
    if is_admin():
        # 当日運用コードセッション: 有効期限と対象ページを毎回確認
        # 管理セッションの期限判定（day ロールは別途 expires で管理）
        if current_role() != "day" and _session_expired():
            _clear_session()
            st.warning("⏰ セッションの有効期限が切れました。もう一度ログインしてください。")
            st.stop()
        _touch_session()

        if current_role() == "day":
            from datetime import datetime as _dt
            _exp = str(st.session_state.get(_DAY_EXPIRES_KEY) or "")
            try:
                _expired = _dt.now(_JST) >= _dt.fromisoformat(_exp)
            except Exception:
                _expired = True
            # 管理者が「失効」した場合は既存セッションも即切断（レビュー指摘対応）
            if not _expired:
                try:
                    import db as _db
                    _expired = not _db.is_day_code_active(
                        st.session_state.get(_DAY_CODE_ID_KEY))
                except Exception:
                    _expired = True
            if _expired:
                for _k in (_SESSION_KEY, _LOGIN_AT_KEY, _LOGIN_AS_KEY, _ROLE_KEY,
                           _DAY_EXPIRES_KEY, _DAY_CODE_ID_KEY):
                    st.session_state.pop(_k, None)
                st.warning("⏰ 当日運用コードの有効期限が切れました。再ログインしてください。")
                st.rerun()
            if allow_day_code:
                return
            st.markdown("## ⛔ このページは当日運用コードでは入れません")
            st.error(
                f"「{page_name or 'このページ'}」は管理者専用です。"
                "当日運用コードで入れるのはピット端末・出退勤のみです。"
            )
            admin_logout_button()
            st.stop()
        if _role_allowed(current_role(), roles):
            return
        st.markdown("## ⛔ アクセス権限が足りません")
        st.error(
            f"このページ（{page_name or '管理者専用'}）の閲覧には "
            f"ロール {list(roles)} が必要です（現在のロール: {current_role() or '不明'}）。"
            "別の権限のユーザーでログインし直すか、管理者にロール変更を依頼してください。"
        )
        admin_logout_button()
        st.stop()

    # --- TOTPコード入力待ち（パスワードは通過済み・2段階目） ---
    if st.session_state.get(_TOTP_PENDING_KEY):
        _render_totp_form(page_name)
        st.stop()

    users = _load_app_users()

    # パスワード変更待ち（初回ログイン）は他の何より先に処理する
    _pending_pw = st.session_state.get(_PWCHANGE_PENDING_KEY)
    if _pending_pw:
        _render_password_change(dict(_pending_pw))

    # --- モード1: 多ユーザー（ID/PASS＋ロール） ---
    if users:
        st.markdown("## 🔒 ログインが必要です")
        st.caption(
            f"このページ（{page_name or '管理者専用'}）はスタッフの本名・住所・支払額・"
            "契約書PDFを扱います。閲覧・操作にはログインが必要です。"
        )
        with st.form("__app_login_form__"):
            username = st.text_input("ユーザーID", value="", placeholder="例: nakano")
            pw = st.text_input("パスワード", type="password")
            submitted = st.form_submit_button("🔓 ログイン", type="primary")
        if submitted:
            import time
            role = _authenticate(username, pw)
            time.sleep(0.15)  # タイミング攻撃の弱体化
            if role:
                _u = (username or "").strip()[:40]
                # 管理者が設定した初期パスワードのままなら、本人に変更させてから通す
                # （＝最終的に本人以外はパスワードを知らない状態にする）
                if _must_change_password(_u):
                    st.session_state[_PWCHANGE_PENDING_KEY] = {
                        "user": _u, "role": role, "page_name": page_name or "",
                    }
                    st.rerun()
                _finish_or_totp(username=_u, role=role, account=_u or "admin",
                                page_name=page_name)
            else:
                _log_safe("admin_login_failed", "auth",
                          detail=f"page={page_name}, user={(username or '').strip()[:40]}",
                          performed_by=(username or "").strip()[:40] or "unknown")
                st.error("❌ ユーザーIDまたはパスワードが違います")
            _monitor_login_failure("管理者ログイン（多ユーザー）", f"入力ID: {username!r}")
        if allow_day_code:
            _render_day_code_form(page_name)
        st.stop()

    # --- fail closed: [auth.users] はあるが有効ユーザーが0件 ---
    # （password_hash の欠落・形式不正で全entryが無効）。
    # ここでパスワードレス(dev)に落とすと無認証アクセスを許してしまうので、必ずブロックする。
    if _auth_users_configured():
        st.markdown("## 🔒 認証設定エラー")
        st.error(
            "認証ユーザー（[auth.users]）が正しく設定されていません"
            "（password_hash の欠落・形式不正）。安全のためこのページをブロックしました。\n\n"
            "管理者対応: `scripts/make_app_user.py` でユーザーを再生成し、"
            'Secrets の `[auth.users."<ID>"]` と `password_hash`（`pbkdf2$...`）を見直してください。'
        )
        st.stop()

    # --- モード2: 単一パスワード（後方互換） ---
    expected = _get_admin_password()
    if not expected:
        # --- モード3: パスワードレス ---
        # 2026-07-29: 従来はここで警告して素通り（fail-open）させていたが、
        # ADMIN_PASSWORD の設定漏れが「動いているデプロイ」として通ってしまい、
        # 全ページが無認証で開く事故になりうるため fail-closed に変更した。
        # ローカル開発でだけ P1_ALLOW_NO_AUTH=1 で明示的に無効化できる。
        if str(_os.environ.get("P1_ALLOW_NO_AUTH", "")).strip() not in ("1", "true", "True"):
            st.error(
                "🔒 **認証が設定されていないため、このページをブロックしました。**\n\n"
                "管理者対応: 環境変数（またはSecrets）に `ADMIN_PASSWORD` を設定して"
                "再起動してください。ローカル開発で認証を外す場合のみ "
                "`P1_ALLOW_NO_AUTH=1` を指定します。"
            )
            st.stop()
        st.warning("⚠️ 認証なしモード（P1_ALLOW_NO_AUTH=1）で動作しています。", icon="🔓")
        return

    st.markdown("## 🔒 管理者認証が必要です")
    st.caption(
        f"このページ（{page_name or '管理者専用'}）はスタッフの本名・住所・支払額・"
        "契約書PDFを扱います。閲覧・操作には管理者パスワードが必要です。"
    )
    with st.form("__admin_login_form__"):
        operator = st.text_input("オペレーター名（任意）", value="",
                                 placeholder="例: 中野 / 伊藤",
                                 help="操作ログに記録される名前。誰が触ったかの追跡用。")
        pw = st.text_input("管理者パスワード", type="password",
                           placeholder="Streamlit Secrets の ADMIN_PASSWORD")
        submitted = st.form_submit_button("🔓 ログイン", type="primary")
    if submitted:
        ok = (
            isinstance(pw, str) and isinstance(expected, str)
            and len(pw) == len(expected) and _consteq(pw, expected)
        )
        import time
        time.sleep(0.15)
        if ok:
            _op = ((operator or "").strip() or "anonymous_admin")[:30]
            _finish_or_totp(username=_op, role="admin", account="admin",
                            page_name=page_name)
        else:
            _log_safe("admin_login_failed", "auth",
                      detail=f"page={page_name}, pw_len={len(pw or '')}, by={operator[:30] if operator else 'anon'}",
                      performed_by=operator[:30] or "anonymous")
            st.error("❌ パスワードが違います")
            _monitor_login_failure("管理者パスワード")
    if allow_day_code:
        _render_day_code_form(page_name)
    st.stop()



# ============================================================
# 2段階認証（TOTP）と当日運用コード（2026-07-28 追加）
# ============================================================
def _finish_login(user: str, role: str, page_name: str, note: str = "") -> None:
    """認証確定（セッション設定→ログ→再描画）。"""
    st.session_state[_SESSION_KEY] = True
    st.session_state[_LOGIN_AT_KEY] = datetime.now(_JST).strftime("%Y-%m-%d %H:%M:%S")
    st.session_state[_LOGIN_AS_KEY] = (user or "anonymous_admin")[:40]
    st.session_state[_ROLE_KEY] = role
    try:
        import db as _db
        _db.touch_app_user_login(user or "")
    except Exception:
        pass
    _log_safe("admin_login", "auth",
              detail=f"page={page_name}, user={(user or '')[:40]}, role={role}{note}",
              performed_by=(user or "admin")[:40])
    st.rerun()


def _finish_or_totp(*, username: str, role: str, account: str, page_name: str) -> None:
    """パスワード通過後、TOTPが有効なら2段階目へ。無効なら即ログイン確定。"""
    totp_cfg = None
    try:
        import db as _db
        totp_cfg = _db.get_totp(account)
    except Exception as _e:
        # 2026-07-29 修正: 以前はDB障害時に「TOTPなし」とみなしてログインを通していた
        # （fail-open）。2要素認証を設定している意味が消えるため、確認できないときは
        # ログインを拒否する（fail-closed）。復旧手順は画面に案内する。
        _is_lookup_failure = type(_e).__name__ == "TotpLookupError"
        if _is_lookup_failure:
            st.error(
                "🔒 **2要素認証の設定を確認できなかったため、ログインを中止しました。**\n\n"
                "データベースに接続できていない可能性があります。"
                "時間をおいて再試行してください。復旧しない場合は管理者に連絡してください。"
            )
            st.stop()
        totp_cfg = None
    if totp_cfg and totp_cfg.get("secret"):
        st.session_state[_TOTP_PENDING_KEY] = {
            "user": username, "role": role, "account": account,
        }
        st.rerun()
    _finish_login(username, role, page_name)


def _render_totp_form(page_name: str) -> None:
    """2段階目: 認証アプリの6桁コード入力。"""
    pend = st.session_state.get(_TOTP_PENDING_KEY) or {}
    st.markdown("## 🔐 2段階認証")
    st.caption("認証アプリ（Google Authenticator等）に表示されている6桁コードを入力してください。")
    st.caption(
        "🆘 認証アプリが使えない場合（スマホ紛失等）: Supabaseダッシュボード → "
        "`p1_admin_totp` テーブルの該当行を削除すると2段階認証が解除され、"
        "パスワードのみでログインできます。"
    )
    with st.form("__totp_form__"):
        code = st.text_input("6桁コード", max_chars=6)
        col_a, col_b = st.columns(2)
        with col_a:
            ok = st.form_submit_button("🔓 認証", type="primary")
        with col_b:
            back = st.form_submit_button("← 戻る")
    if back:
        st.session_state.pop(_TOTP_PENDING_KEY, None)
        st.rerun()
    if ok:
        import time
        time.sleep(0.15)
        valid = False
        try:
            import pyotp
            import db as _db
            cfg = _db.get_totp(pend.get("account") or "admin")
            valid = bool(cfg and pyotp.TOTP(cfg["secret"]).verify(
                (code or "").strip(), valid_window=1))
        except Exception:
            valid = False
        if valid:
            st.session_state.pop(_TOTP_PENDING_KEY, None)
            _finish_login(pend.get("user") or "admin", pend.get("role") or "admin",
                          page_name, note=", totp=ok")
        else:
            _log_safe("totp_failed", "auth",
                      detail=f"page={page_name}, user={pend.get('user')}",
                      performed_by=str(pend.get("user") or "unknown")[:40])
            st.error("❌ コードが違います。時計のずれがある場合は次のコードでもう一度。")
            _monitor_login_failure("2要素認証")


def _render_day_code_form(page_name: str) -> None:
    """当日運用コードでの入室フォーム（ピット端末・出退勤のみ有効）。"""
    with st.expander("🎫 当日運用コードで入る（TD・給与窓口用）", expanded=False):
        st.caption(
            "管理者から受け取った**本日のコード**で入室できます（翌朝5時に自動失効）。"
            "操作できるのはピット端末・出退勤のみです。"
        )
        _fails = int(st.session_state.get(_DAY_FAILS_KEY) or 0)
        if _fails >= 5:
            st.error("試行回数の上限に達しました。ページを閉じて管理者にコードを確認してください。")
            return
        with st.form("__day_code_form__"):
            op = st.text_input("名前（必須・操作記録に残ります）", placeholder="例: 山田")
            code = st.text_input("当日運用コード（8桁）", max_chars=8)
            sub = st.form_submit_button("🎫 入室", type="primary")
        if sub:
            import time
            time.sleep(0.15 * (1 + _fails))  # 失敗ごとに待ち時間を増加
            if not (op or "").strip():
                st.error("名前を入力してください")
                return
            info = None
            try:
                import db as _db
                info = _db.verify_day_code((code or "").strip())
            except Exception:
                info = None
            if info:
                st.session_state[_SESSION_KEY] = True
                st.session_state[_LOGIN_AT_KEY] = datetime.now(_JST).strftime("%Y-%m-%d %H:%M:%S")
                st.session_state[_LOGIN_AS_KEY] = (op or "").strip()[:40]
                st.session_state[_ROLE_KEY] = "day"
                st.session_state[_DAY_EXPIRES_KEY] = str(info.get("expires_at") or "")
                st.session_state[_DAY_CODE_ID_KEY] = info.get("id")
                st.session_state.pop(_DAY_FAILS_KEY, None)
                _log_safe("day_code_login", "auth",
                          detail=f"page={page_name}, by={(op or '').strip()[:40]}, "
                                 f"valid_date={info.get('valid_date')}",
                          performed_by=(op or "").strip()[:40])
                st.rerun()
            else:
                _log_safe("day_code_failed", "auth",
                          detail=f"page={page_name}, by={(op or '').strip()[:40]}",
                          performed_by=(op or "").strip()[:40] or "unknown")
                st.session_state[_DAY_FAILS_KEY] = _fails + 1
                st.error("❌ コードが無効か、期限切れです。管理者に本日のコードを確認してください。")
                _monitor_login_failure("当日運用コード", f"入力者: {op!r}")


def admin_logout_button() -> None:
    """認証済みのときだけサイドバーにログアウトボタンを表示。"""
    if is_admin():
        operator = st.session_state.get(_LOGIN_AS_KEY) or "—"
        role = current_role()
        login_at = admin_login_at()
        with st.sidebar:
            st.caption(f"🔐 {operator}（{role or '—'}） {login_at}")
            if st.button("🔓 ログアウト", use_container_width=True):
                _log_safe("admin_logout", "auth",
                          detail=f"by={operator}", performed_by=operator)
                for k in (_SESSION_KEY, _LOGIN_AT_KEY, _LOGIN_AS_KEY, _ROLE_KEY):
                    st.session_state[k] = "" if k != _SESSION_KEY else False
                st.rerun()


# ============================================================
# Internal
# ============================================================
def _consteq(a: str, b: str) -> bool:
    """定数時間比較（長さは事前に揃えている前提）。"""
    return hmac.compare_digest(a, b)


def _log_safe(action: str, target_type: str, *, detail: str = "",
              performed_by: str = "system") -> None:
    """ログ書き込み失敗時はサイレント（DB接続エラーで認証画面が壊れないように）。"""
    try:
        import db  # type: ignore
        db.log_action(action, target_type, detail=detail, performed_by=performed_by)
    except Exception:
        pass
