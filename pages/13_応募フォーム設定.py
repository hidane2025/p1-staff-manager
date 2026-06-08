"""P1 Staff Manager — 応募フォーム設定（大会↔GSS の登録・案A）

大会を選び、その大会のディーラー応募フォーム(GSS)のURLを登録する。
登録された対応(p1_application_sources)をGASが巡回して応募を自動取込する。
新しい大会は「ここでURLを貼るだけ」で連動に乗る（GAS/コード編集は不要）。
"""

import os
import re
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db

st.set_page_config(page_title="応募フォーム設定", page_icon="📥", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style
from utils.admin_guard import require_admin, admin_logout_button, is_auth_enabled

apply_global_style()
hide_staff_only_pages()
require_admin(page_name="応募フォーム設定")
admin_logout_button()

# fail closed: 認証未設定（パスワードレスdev）では service_role を使う本ページを開かない。
if not is_auth_enabled():
    st.error(
        "⛔ このページは認証が有効な環境でのみ利用できます。"
        "Streamlit Secrets に `[auth.users]`（推奨）または `ADMIN_PASSWORD` を設定してください。"
    )
    st.stop()

st.title("📥 応募フォーム設定")
st.caption("大会ごとのディーラー応募フォーム（Googleフォーム→スプレッドシート）を登録します。"
           "登録すると、その大会の新規応募が自動で取り込まれます。")


def _extract_spreadsheet_id(url_or_id: str) -> str:
    """GSSのURLまたはIDからスプレッドシートIDを取り出す。"""
    s = (url_or_id or "").strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", s)
    if m:
        return m.group(1)
    # 既にIDだけが渡された場合（44文字前後の英数字）はそのまま
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", s):
        return s
    return ""


# --- グレースフル: 未デプロイ/未設定なら案内して停止 ---
if not db.applications_enabled():
    st.info(
        "応募連動はまだ有効化されていません。利用するには次が必要です：\n\n"
        "1. Supabase に応募テーブルのマイグレーション "
        "（`docs/db_migrations/20260608_add_dealer_applications.sql`）を適用\n"
        "2. Streamlit Secrets に **`SUPABASE_SERVICE_KEY`**（service_role キー）を設定\n\n"
        "（設定後にこの画面が使えるようになります）",
        icon="🔌",
    )
    st.stop()

events = db.get_all_events() or []
if not events:
    st.warning("先に「イベント設定」で大会を登録してください。")
    st.stop()

# === 新規登録 ===
st.subheader("新しい応募フォームを登録")
with st.form("__add_source__"):
    # 同名＋同日付の大会が潰れないよう #ID も含めて一意化する。
    ev_labels = {f'{e.get("name","(無題)")}（{e.get("start_date","")} #{e["id"]}）': e["id"]
                 for e in events}
    ev_choice = st.selectbox("対象の大会", list(ev_labels.keys()))
    url = st.text_input("応募フォームのスプレッドシートURL",
                        placeholder="https://docs.google.com/spreadsheets/d/xxxx/edit")
    col1, col2 = st.columns(2)
    with col1:
        label = st.text_input("表示名（任意）", placeholder="例: OSAKA SUMMER")
    with col2:
        sheet_name = st.text_input("回答シート名", value="フォームの回答 1",
                                   help="GoogleフォームのGSSタブ名。通常は『フォームの回答 1』")
    submitted = st.form_submit_button("➕ 登録", type="primary")

if submitted:
    ssid = _extract_spreadsheet_id(url)
    if not ssid:
        st.error("スプレッドシートのURL（またはID）を正しく入力してください。")
    else:
        try:
            db.add_application_source(
                event_id=ev_labels[ev_choice], label=label,
                spreadsheet_id=ssid, sheet_name=sheet_name,
            )
            st.success(f"登録しました（ID: {ssid[:8]}…）。10分以内に取込が始まります。")
            st.rerun()
        except Exception as e:
            st.error(f"登録に失敗しました: {e}")

st.divider()

# === 既存の対応一覧 ===
st.subheader("登録済みの応募フォーム")
sources = db.get_application_sources()
if not sources:
    st.caption("まだ登録がありません。")
else:
    ev_name = {e["id"]: e.get("name", "(無題)") for e in events}
    for s in sources:
        c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
        with c1:
            st.write(f'**{s.get("label") or "(名称なし)"}**')
            st.caption(f'大会: {ev_name.get(s.get("event_id"), "?")}')
        with c2:
            st.caption(f'ID: {str(s.get("spreadsheet_id",""))[:14]}…')
            st.caption(f'シート: {s.get("sheet_name","")}')
        with c3:
            st.write("🟢 有効" if s.get("is_active") else "⚪️ 停止中")
        with c4:
            if s.get("is_active"):
                if st.button("停止", key=f"off_{s['id']}"):
                    db.set_source_active(s["id"], False)
                    st.rerun()
            else:
                if st.button("再開", key=f"on_{s['id']}", type="primary"):
                    db.set_source_active(s["id"], True)
                    st.rerun()
