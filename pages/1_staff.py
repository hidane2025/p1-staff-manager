"""P1 Staff Manager — スタッフ管理ページ"""

import streamlit as st
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db

st.set_page_config(page_title="スタッフ管理", page_icon="📋", layout="wide")
st.title("📋 スタッフ管理")

ROLES = ["Dealer", "Floor", "TD", "DC", "Chip"]

# --- 検索 ---
st.subheader("スタッフ検索")
col_search, col_role = st.columns([3, 1])
with col_search:
    search_query = st.text_input("🔍 名前・NO.で検索", placeholder="例: EveKat, 18")
with col_role:
    role_filter = st.selectbox("役職フィルタ", ["すべて"] + ROLES)

role_val = None if role_filter == "すべて" else role_filter
search_val = search_query if search_query else None
staff_list = db.get_all_staff(role_filter=role_val, search=search_val)

# --- 一覧表示 ---
st.subheader(f"スタッフ一覧（{len(staff_list)}名）")

if staff_list:
    header_cols = st.columns([0.8, 1, 2, 2, 1.2, 2, 0.8])
    headers = ["NO.", "役職", "名前（日本語）", "名前（英語）", "連絡先", "メモ", "編集"]
    for col, h in zip(header_cols, headers):
        col.markdown(f"**{h}**")

    st.divider()

    for s in staff_list:
        cols = st.columns([0.8, 1, 2, 2, 1.2, 2, 0.8])
        cols[0].write(s["no"] or "—")
        cols[1].write(s["role"])
        cols[2].write(s["name_jp"])
        cols[3].write(s["name_en"] or "—")
        cols[4].write(s["contact"] or "—")
        cols[5].write(s["notes"] or "—")
        if cols[6].button("✏️", key=f"edit_{s['id']}"):
            st.session_state["editing_staff_id"] = s["id"]
else:
    st.info("スタッフが登録されていません。下のフォームから登録するか、シフト取込で一括登録できます。")

# --- 編集モーダル ---
if "editing_staff_id" in st.session_state:
    edit_id = st.session_state["editing_staff_id"]
    staff = db.get_staff_by_id(edit_id)
    if staff:
        st.divider()
        st.subheader(f"✏️ 編集: {staff['name_jp']}")
        with st.form(f"edit_form_{edit_id}"):
            e_no = st.number_input("NO.", value=staff["no"] or 0, step=1)
            e_name_jp = st.text_input("名前（日本語）", value=staff["name_jp"])
            e_name_en = st.text_input("名前（英語）", value=staff["name_en"] or "")
            e_role = st.selectbox("役職", ROLES, index=ROLES.index(staff["role"]) if staff["role"] in ROLES else 0)
            e_contact = st.text_input("連絡先", value=staff["contact"] or "")
            e_notes = st.text_area("メモ", value=staff["notes"] or "")

            col_save, col_cancel = st.columns(2)
            submitted = col_save.form_submit_button("💾 保存", type="primary")
            cancelled = col_cancel.form_submit_button("キャンセル")

            if submitted:
                db.update_staff(edit_id, no=e_no, name_jp=e_name_jp, name_en=e_name_en,
                                role=e_role, contact=e_contact, notes=e_notes)
                del st.session_state["editing_staff_id"]
                st.success(f"{e_name_jp} を更新しました")
                st.rerun()
            if cancelled:
                del st.session_state["editing_staff_id"]
                st.rerun()

# --- 新規登録 ---
st.divider()
st.subheader("➕ スタッフ新規登録")
with st.form("add_staff_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        new_no = st.number_input("NO.", value=0, step=1, min_value=0)
        new_name_jp = st.text_input("名前（日本語）", placeholder="例: EveKat")
    with col2:
        new_name_en = st.text_input("名前（英語）", placeholder="例: EVEKAT")
        new_role = st.selectbox("役職", ROLES)
    with col3:
        new_contact = st.text_input("連絡先", placeholder="例: LINE ID")
        new_notes = st.text_area("メモ", placeholder="例: MIXテーブル対応可")

    if st.form_submit_button("➕ 登録", type="primary"):
        if new_name_jp:
            db.create_staff(new_no, new_name_jp, new_name_en, new_role, new_contact, new_notes)
            st.success(f"{new_name_jp}（{new_role}）を登録しました")
            st.rerun()
        else:
            st.error("名前は必須です")
