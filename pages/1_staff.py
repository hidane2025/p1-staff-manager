"""P1 Staff Manager — スタッフ管理ページ v3"""

import streamlit as st
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db

st.set_page_config(page_title="スタッフ管理", page_icon="📋", layout="wide")
st.title("📋 スタッフ管理")

ROLES = ["Dealer", "Floor", "TD", "DC", "Chip"]
EMPLOYMENT_TYPES = {
    "contractor": "業務委託",
    "timee": "タイミー",
    "fulltime": "正社員",
}
EMPLOYMENT_LABELS = list(EMPLOYMENT_TYPES.values())

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
    header_cols = st.columns([0.7, 0.8, 1.3, 1, 1.3, 1, 1.3, 0.8, 0.6])
    headers = ["NO.", "役職", "名前", "本名", "メール", "雇用区分", "備考", "住所", "編集"]
    for col, h in zip(header_cols, headers):
        col.markdown(f"**{h}**")
    st.divider()

    for s in staff_list:
        cols = st.columns([0.7, 0.8, 1.3, 1, 1.3, 1, 1.3, 0.8, 0.6])
        cols[0].write(s["no"] or "—")
        cols[1].write(s["role"])
        cols[2].write(s["name_jp"])
        cols[3].write(s.get("real_name") or "—")
        cols[4].write(s.get("email") or "—")
        emp_type = s.get("employment_type") or "contractor"
        cols[5].write(EMPLOYMENT_TYPES.get(emp_type, emp_type))
        cols[6].write(s.get("notes") or "—")
        cols[7].write("📍" if s.get("address") else "—")
        if cols[8].button("✏️", key=f"edit_{s['id']}"):
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
            col_basic1, col_basic2, col_basic3 = st.columns(3)
            with col_basic1:
                e_no = st.number_input("NO.", value=staff["no"] or 0, step=1)
                e_name_jp = st.text_input("名前（日本語/ディーラーネーム）", value=staff["name_jp"])
            with col_basic2:
                e_name_en = st.text_input("名前（英語）", value=staff["name_en"] or "")
                e_real_name = st.text_input("本名", value=staff.get("real_name") or "",
                                             help="領収書に記載する氏名")
            with col_basic3:
                e_role = st.selectbox("役職", ROLES,
                                       index=ROLES.index(staff["role"]) if staff["role"] in ROLES else 0)
                emp_keys = list(EMPLOYMENT_TYPES.keys())
                current_emp = staff.get("employment_type") or "contractor"
                emp_idx = emp_keys.index(current_emp) if current_emp in emp_keys else 0
                e_employment = st.selectbox("雇用区分", emp_keys,
                                             format_func=lambda k: EMPLOYMENT_TYPES[k],
                                             index=emp_idx)

            col_contact1, col_contact2 = st.columns(2)
            with col_contact1:
                e_email = st.text_input("メールアドレス", value=staff.get("email") or "",
                                         help="領収書発行用")
                e_contact = st.text_input("連絡先（LINE等）", value=staff["contact"] or "")
            with col_contact2:
                e_address = st.text_area("住所", value=staff.get("address") or "",
                                          help="領収書に記載する住所", height=80)

            # タイミー用の個別時給
            e_custom_rate = None
            if e_employment == "timee":
                e_custom_rate = st.number_input(
                    "個別時給（円） ※タイミーのみ",
                    value=staff.get("custom_hourly_rate") or 1500,
                    step=50, min_value=0,
                    help="タイミー経由の場合、イベントのレートではなく個別時給が適用されます",
                )
            else:
                e_custom_rate = staff.get("custom_hourly_rate")

            e_notes = st.text_area("備考・メモ", value=staff.get("notes") or "",
                                    help="イレギュラー対応など自由入力")

            col_save, col_cancel = st.columns(2)
            submitted = col_save.form_submit_button("💾 保存", type="primary")
            cancelled = col_cancel.form_submit_button("キャンセル")

            if submitted:
                db.update_staff(
                    edit_id, no=e_no, name_jp=e_name_jp, name_en=e_name_en,
                    role=e_role, contact=e_contact, notes=e_notes,
                    real_name=e_real_name, address=e_address, email=e_email,
                    employment_type=e_employment,
                    custom_hourly_rate=e_custom_rate,
                )
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
        new_name_jp = st.text_input("名前（日本語/ディーラーネーム）", placeholder="例: EveKat")
        new_real_name = st.text_input("本名", placeholder="例: 山田太郎")
    with col2:
        new_name_en = st.text_input("名前（英語）", placeholder="例: EVEKAT")
        new_role = st.selectbox("役職", ROLES)
        new_employment = st.selectbox(
            "雇用区分",
            list(EMPLOYMENT_TYPES.keys()),
            format_func=lambda k: EMPLOYMENT_TYPES[k],
        )
    with col3:
        new_email = st.text_input("メールアドレス", placeholder="example@mail.com")
        new_contact = st.text_input("連絡先（LINE等）", placeholder="例: LINE ID")
        new_custom_rate = None
        if new_employment == "timee":
            new_custom_rate = st.number_input("個別時給（円）", value=1500, step=50, min_value=0)

    new_address = st.text_input("住所", placeholder="例: 〒100-0001 東京都千代田区...")
    new_notes = st.text_area("備考・メモ", placeholder="例: MIXテーブル対応可、イレギュラー対応")

    if st.form_submit_button("➕ 登録", type="primary"):
        if new_name_jp:
            try:
                db.create_staff(
                    no=new_no, name_jp=new_name_jp, name_en=new_name_en,
                    role=new_role, contact=new_contact, notes=new_notes,
                    real_name=new_real_name, address=new_address, email=new_email,
                    employment_type=new_employment,
                    custom_hourly_rate=new_custom_rate,
                )
                st.success(f"{new_name_jp}（{EMPLOYMENT_TYPES[new_employment]}/{new_role}）を登録しました")
                st.rerun()
            except ValueError as e:
                st.error(f"❌ {e}")
        else:
            st.error("名前は必須です")
