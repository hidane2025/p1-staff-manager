"""P1 Staff Manager — アカウント管理（2026-07-29 新設）

画面からログインアカウントを追加・変更・無効化する。
従来はコマンド実行と再デプロイが必要だったため、2人目以降を迎えにくかった。

設計:
    ・管理者が初期パスワードを決めて本人に渡す
    ・本人の初回ログインで変更を強制する（→ 以後は本人しか知らない）
    ・辞めた人は「無効化」する。削除しないのは監査ログとの紐付けを残すため
"""

from __future__ import annotations

import secrets as _secrets
import string

import streamlit as st

import db

st.set_page_config(page_title="アカウント管理", page_icon="👤", layout="wide")
from utils.ui_helpers import hide_staff_only_pages  # noqa: E402
from utils.page_layout import apply_global_style, page_header  # noqa: E402
from utils.admin_guard import (  # noqa: E402
    require_admin, admin_logout_button, operator_name, current_user,
)

apply_global_style()
hide_staff_only_pages()
require_admin(page_name="アカウント管理")
admin_logout_button()

page_header(
    "👤 アカウント管理",
    "このシステムにログインできる人を管理します。"
    "承認・支払の操作履歴は、ここで作ったアカウントごとに記録されます。",
)

_me = current_user()


def _suggest_password(length: int = 14) -> str:
    """初期パスワードの候補を作る（紛らわしい文字は除く）。"""
    alphabet = "".join(c for c in (string.ascii_letters + string.digits)
                       if c not in "0OoIl1")
    return "".join(_secrets.choice(alphabet) for _ in range(length))


# ============================================================
# マイグレーション未適用の案内
# ============================================================
try:
    _users = db.list_app_users()
    _table_ready = True
except Exception:
    _users, _table_ready = [], False

if not _table_ready:
    st.error(
        "データベースの準備ができていません。"
        "`docs/db_migrations/20260729_add_app_users.sql` を Supabase で実行してください。"
    )
    st.stop()


# ============================================================
# 現状の警告（アカウントが1つも無い＝共有パスワード運用のまま）
# ============================================================
if not _users:
    st.warning(
        "⚠️ **まだ個人アカウントが1つもありません。**\n\n"
        "現在は全員が同じパスワードでログインしているため、"
        "操作履歴の「誰が」が自己申告になっています。\n\n"
        "下のフォームで、まずご自身のアカウントを作ってください。"
        "**1つ目を作ると、次回ログインから個人アカウント方式に切り替わります**"
        "（共有パスワードでは入れなくなります）。関係者全員分を続けて作成してください。",
        icon="⚠️",
    )

_active_admins = [u for u in _users if u.get("active") and u.get("role") == "admin"]


# ============================================================
# 一覧
# ============================================================
st.subheader("登録されているアカウント")

if _users:
    for u in _users:
        uname = u["username"]
        is_me = (uname == _me)
        cols = st.columns([3, 2, 2, 2, 2])
        with cols[0]:
            label = f"**{uname}**"
            if u.get("display_name"):
                label += f"（{u['display_name']}）"
            if is_me:
                label += "　🫵 自分"
            st.markdown(label)
            st.caption(
                f"作成: {str(u.get('created_at') or '')[:10]}　"
                f"最終ログイン: {str(u.get('last_login_at') or '—')[:16]}"
            )
        with cols[1]:
            st.write("🟢 有効" if u.get("active") else "⚫ 無効")
        with cols[2]:
            st.write("👑 管理者" if u.get("role") == "admin" else "👀 閲覧のみ")
        with cols[3]:
            if u.get("must_change_password"):
                st.write("🔑 初期PWのまま")
            else:
                st.write("✅ 本人が設定済み")
        with cols[4]:
            with st.popover("⚙️ 変更"):
                st.caption(f"「{uname}」の設定")

                # 権限の変更（自分の管理者権限は外せない＝締め出し防止）
                _new_role = st.selectbox(
                    "権限", ["admin", "viewer"],
                    index=0 if u.get("role") == "admin" else 1,
                    format_func=lambda r: "管理者（全操作）" if r == "admin" else "閲覧のみ",
                    key=f"role_{uname}",
                )
                if _new_role != u.get("role"):
                    _last_admin = (u.get("role") == "admin" and len(_active_admins) <= 1)
                    if _last_admin:
                        st.error("最後の管理者の権限は変更できません（全員が締め出されるため）。")
                    elif st.button("権限を変更", key=f"rolebtn_{uname}"):
                        ok, msg = db.update_app_user(
                            uname, role=_new_role, performed_by=operator_name())
                        (st.success if ok else st.error)(msg)
                        if ok:
                            st.rerun()

                st.divider()

                # 有効・無効
                if u.get("active"):
                    _last_admin = (u.get("role") == "admin" and len(_active_admins) <= 1)
                    if _last_admin:
                        st.caption("最後の管理者は無効化できません。")
                    elif st.button("⚫ 無効にする（ログイン不可）", key=f"off_{uname}"):
                        ok, msg = db.update_app_user(
                            uname, active=False, performed_by=operator_name())
                        (st.success if ok else st.error)(msg)
                        if ok:
                            st.rerun()
                else:
                    if st.button("🟢 有効に戻す", key=f"on_{uname}"):
                        ok, msg = db.update_app_user(
                            uname, active=True, performed_by=operator_name())
                        (st.success if ok else st.error)(msg)
                        if ok:
                            st.rerun()

                st.divider()

                # パスワードのリセット（本人が忘れた場合）
                st.caption(
                    "パスワードを忘れた場合はここでリセットします。"
                    "新しい初期パスワードを本人に伝えてください（次回ログインで本人が変更します）。"
                )
                _reset_pw = st.text_input(
                    "新しい初期パスワード", value=_suggest_password(),
                    key=f"pw_{uname}",
                )
                if st.button("🔑 パスワードをリセット", key=f"pwbtn_{uname}"):
                    ok, msg = db.set_app_user_password(
                        uname, _reset_pw, must_change=True, performed_by=operator_name())
                    if ok:
                        st.success("リセットしました。上の値を本人に伝えてください。")
                    else:
                        st.error(msg)
else:
    st.info("まだアカウントがありません。")


# ============================================================
# 追加
# ============================================================
st.divider()
st.subheader("➕ アカウントを追加")

st.caption(
    "初期パスワードは自動で候補を用意しています。そのまま使って構いません。"
    "**本人が初回ログインしたときに変更を求められる**ので、"
    "最終的には本人しか知らないパスワードになります。"
)

if "new_user_pw" not in st.session_state:
    st.session_state["new_user_pw"] = _suggest_password()

with st.form("__add_user__"):
    c1, c2 = st.columns(2)
    with c1:
        new_username = st.text_input(
            "ログインID *", placeholder="例: ito",
            help="半角英数字。ローマ字の姓が分かりやすいです。",
        )
        new_display = st.text_input("表示名（任意）", placeholder="例: 伊藤")
    with c2:
        new_role = st.selectbox(
            "権限 *", ["admin", "viewer"],
            format_func=lambda r: "管理者（承認・支払を含む全操作）" if r == "admin"
            else "閲覧のみ（金額の確認だけ）",
        )
        new_pw = st.text_input("初期パスワード *", value=st.session_state["new_user_pw"])

    submitted = st.form_submit_button("➕ このアカウントを作成", type="primary")

if submitted:
    ok, msg = db.create_app_user(
        new_username, new_pw, role=new_role,
        display_name=new_display, performed_by=operator_name(),
    )
    if ok:
        st.success(msg)
        st.info(
            f"**本人に伝える情報**\n\n"
            f"- ログインID: `{new_username.strip()}`\n"
            f"- 初期パスワード: `{new_pw}`\n\n"
            "初回ログイン時に、本人がパスワードを変更します。"
            "この画面を閉じると初期パスワードは再表示できません"
            "（忘れた場合は上の一覧からリセットしてください）。",
            icon="📋",
        )
        st.session_state["new_user_pw"] = _suggest_password()
    else:
        st.error(msg)


# ============================================================
# 補足
# ============================================================
st.divider()
with st.expander("💡 このページの考え方"):
    st.markdown(
        """
- **玄関の鍵（ブラウザが最初に聞いてくる認証）は全員で共有**します。
  無関係な人を止めるための壁で、誰が通ったかまでは問いません。
- **部屋の鍵（このページで作るアカウント）は1人1つ**にします。
  承認・支払の記録が実在の個人と結びつく必要があるためです。
- 辞めた人は **削除ではなく「無効化」** します。過去の操作履歴との
  紐付けを残したまま、ログインだけを止められます。
- **最後の管理者は無効化も権限変更もできません**。全員が締め出される事故を防ぐためです。
        """
    )
