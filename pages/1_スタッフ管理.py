"""P1 Staff Manager — スタッフ管理ページ v3"""

import streamlit as st
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db

st.set_page_config(page_title="スタッフ管理", page_icon="👥", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style, page_header, flow_bar
from utils.admin_guard import require_admin, admin_logout_button, operator_name
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="スタッフ管理")
admin_logout_button()

page_header("👥 スタッフ管理", "ディーラー・フロア・TD等のスタッフを登録・編集・一括取込する画面です。")
flow_bar(active="input", done=["setup"])

# PII閲覧監査ログ
db.log_action("view_staff_list", "staff",
              detail=f"page=スタッフ管理", performed_by=operator_name())

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
    # 住所未登録スタッフを警告
    no_address = [s for s in staff_list if not s.get("address")]
    if no_address:
        st.warning(f"⚠️ 住所未登録のスタッフが{len(no_address)}名います（交通費計算に影響）")

    header_cols = st.columns([0.6, 0.8, 1.2, 1, 0.8, 0.8, 1, 1, 0.6, 0.5])
    headers = ["NO.", "役職", "名前", "本名", "地域", "最寄駅", "メール", "備考", "住所", "編集"]
    for col, h in zip(header_cols, headers):
        col.markdown(f"**{h}**")
    st.divider()

    for s in staff_list:
        cols = st.columns([0.6, 0.8, 1.2, 1, 0.8, 0.8, 1, 1, 0.6, 0.5])
        cols[0].write(s["no"] or "—")
        cols[1].write(s["role"])
        cols[2].write(s["name_jp"])
        cols[3].write(s.get("real_name") or "—")
        cols[4].write(s.get("region") or "⚠️未")
        cols[5].write(s.get("nearest_station") or "—")
        cols[6].write(s.get("email") or "—")
        cols[7].write(s.get("notes") or "—")
        cols[8].write("📍" if s.get("address") else "❌")
        if cols[9].button("✏️", key=f"edit_{s['id']}"):
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
                e_nearest = st.text_input("最寄り駅", value=staff.get("nearest_station") or "",
                                           placeholder="例: 名古屋駅")
            with col_contact2:
                e_address = st.text_area("住所", value=staff.get("address") or "",
                                          help="住所から都道府県・地域区分を自動判定", height=80)
                current_pref = staff.get("prefecture")
                current_region = staff.get("region")
                if current_pref or current_region:
                    st.caption(f"判定済み: {current_pref or '-'} / {current_region or '-'}地域")

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
                    nearest_station=e_nearest,
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

    col_addr, col_station = st.columns([2, 1])
    with col_addr:
        new_address = st.text_input("住所", placeholder="例: 〒100-0001 東京都千代田区...",
                                     help="都道府県から入力すると、地域区分が自動判定されます")
    with col_station:
        new_nearest = st.text_input("最寄り駅", placeholder="例: 名古屋駅")
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
                    nearest_station=new_nearest,
                )
                st.success(f"{new_name_jp}（{EMPLOYMENT_TYPES[new_employment]}/{new_role}）を登録しました")
                st.rerun()
            except ValueError as e:
                st.error(f"❌ {e}")
        else:
            st.error("名前は必須です")

# --- 一括登録 ---
st.divider()
st.subheader("📥 スタッフ一括登録/更新")
st.markdown(
    "CSV/TSV形式で複数スタッフを一度に登録/更新できます。"
    "**NO.またはディーラーネーム**で既存と照合し、一致すれば更新、なければ新規作成します。"
)

BULK_TEMPLATE = (
    "no,name_jp,real_name,address,email,nearest_station,role,employment_type,name_en,contact,notes\n"
    "18,EveKat,山田太郎,愛知県名古屋市中区栄1-1-1,taro@example.com,名古屋,Dealer,contractor,EVEKAT,LINE_ID,\n"
    "20,久遠,佐藤花子,大阪府大阪市北区梅田1-1-1,hana@example.com,大阪,Dealer,contractor,KUON,,MIXテーブル対応可\n"
)

import_tab1, import_tab2, import_tab3, import_tab4 = st.tabs([
    "📁 CSVアップロード", "📋 テキスト貼り付け（CSV/TSV）", "✏️ テーブル入力",
    "🔗 Googleフォーム連携",
])

def _run_bulk_import(rows):
    if not rows:
        st.warning("データがありません")
        return
    result = db.bulk_import_staff(rows)
    col_r1, col_r2, col_r3 = st.columns(3)
    col_r1.metric("新規登録", f"{result['created']}名")
    col_r2.metric("更新", f"{result['updated']}名")
    col_r3.metric("エラー", f"{len(result['errors'])}件")
    if result["errors"]:
        with st.expander(f"⚠️ エラー {len(result['errors'])}件"):
            for err in result["errors"]:
                st.error(err)
    if result["created"] + result["updated"] > 0:
        st.success(f"合計 {result['created'] + result['updated']}名を処理しました")
        st.balloons()


with import_tab1:
    st.download_button(
        "📄 テンプレートCSVをダウンロード",
        BULK_TEMPLATE.encode("utf-8-sig"),
        "staff_template.csv",
        "text/csv",
    )
    uploaded = st.file_uploader("CSVファイル", type=["csv", "tsv", "txt"], key="bulk_csv")
    if uploaded:
        # P2#8 (2026-05-04): アップロードサイズの上限チェック（5MB）
        MAX_UPLOAD_SIZE = 5 * 1024 * 1024
        if uploaded.size > MAX_UPLOAD_SIZE:
            st.error(
                f"❌ ファイルが大きすぎます（{uploaded.size / 1024 / 1024:.1f}MB）。"
                f"上限は {MAX_UPLOAD_SIZE / 1024 / 1024:.0f}MB です。"
                "ファイルを分割してアップロードしてください。"
            )
            st.stop()
        import pandas as pd
        content = uploaded.read()
        text = content.decode("utf-8-sig", errors="replace")
        sep = "\t" if "\t" in text.split("\n")[0] else ","
        import io
        df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str).fillna("")
        st.markdown("**プレビュー:**")
        st.dataframe(df.head(10), use_container_width=True, hide_index=True)
        st.caption(f"合計 {len(df)} 行")
        if st.button("🚀 取り込み実行", type="primary", key="csv_import"):
            _run_bulk_import(df.to_dict("records"))

with import_tab2:
    st.markdown(
        "スプレッドシート等からコピーしたデータを貼り付けてください。"
        "1行目はヘッダー（列名）にしてください。"
    )
    pasted = st.text_area(
        "データ（CSVまたはTSV）",
        height=200,
        placeholder=BULK_TEMPLATE,
        key="bulk_paste",
    )
    if pasted.strip():
        import pandas as pd
        import io
        first_line = pasted.strip().split("\n")[0]
        sep = "\t" if "\t" in first_line else ","
        try:
            df = pd.read_csv(io.StringIO(pasted), sep=sep, dtype=str).fillna("")
            st.markdown("**プレビュー:**")
            st.dataframe(df.head(10), use_container_width=True, hide_index=True)
            st.caption(f"合計 {len(df)} 行")
            if st.button("🚀 取り込み実行", type="primary", key="paste_import"):
                _run_bulk_import(df.to_dict("records"))
        except Exception as e:
            st.error(f"パースエラー: {e}")

with import_tab3:
    st.markdown("テーブルに直接入力して一括登録できます。行は下部の「+」で追加。")
    import pandas as pd
    template_df = pd.DataFrame([
        {"no": 0, "name_jp": "", "real_name": "", "address": "",
         "email": "", "nearest_station": "", "role": "Dealer",
         "employment_type": "contractor", "notes": ""}
    ])
    edited = st.data_editor(
        template_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "no": st.column_config.NumberColumn("NO.", min_value=0, step=1),
            "name_jp": st.column_config.TextColumn("ディーラーネーム", required=True),
            "real_name": "本名",
            "address": "住所",
            "email": "メール",
            "nearest_station": "最寄り駅",
            "role": st.column_config.SelectboxColumn("役職", options=ROLES),
            "employment_type": st.column_config.SelectboxColumn(
                "雇用区分", options=list(EMPLOYMENT_TYPES.keys()),
            ),
            "notes": "備考",
        },
        hide_index=True,
        key="bulk_edit_table",
    )
    if st.button("🚀 テーブルから取り込み", type="primary", key="table_import"):
        rows = edited.to_dict("records")
        rows = [r for r in rows if r.get("name_jp")]
        _run_bulk_import(rows)

with import_tab4:
    st.info(
        "📋 **Google フォームで受付情報を収集 → CSVダウンロード → ここにアップロード**\n\n"
        "推奨質問テンプレ（コピペ用）: `docs/gform_staff_onboarding_template.md`\n\n"
        "運用フロー: Googleフォーム作成 → 回答スプレッドシートから「ファイル→ダウンロード→CSV」"
        "→ このタブにアップロード → プレビュー確認 → 「🔄 P1にインポート」"
    )
    from utils.gform_importer import parse_gform_csv, validate_gform_rows
    import pandas as pd

    gform_uploaded = st.file_uploader(
        "Google フォーム回答 CSV",
        type=["csv"],
        key="gform_csv",
        help="Google スプレッドシート→ファイル→ダウンロード→カンマ区切り形式（.csv）で保存",
    )
    if gform_uploaded:
        # P2#8: アップロードサイズの上限チェック（5MB）
        if gform_uploaded.size > 5 * 1024 * 1024:
            st.error("❌ ファイルが大きすぎます（上限5MB）。")
            st.stop()
        try:
            rows = parse_gform_csv(gform_uploaded.read())
        except Exception as exc:
            st.error(f"CSVパースエラー: {exc}")
            rows = []

        if rows:
            st.markdown("**プレビュー（先頭10行）:**")
            preview_df = pd.DataFrame(rows).head(10)
            st.dataframe(preview_df, use_container_width=True, hide_index=True)
            st.caption(f"合計 {len(rows)} 行")

            validation_errors = validate_gform_rows(rows)
            if validation_errors:
                with st.expander(
                    f"⚠️ バリデーションエラー {len(validation_errors)}件（続行は可能）"
                ):
                    for row_no, errs in validation_errors:
                        st.warning(f"行{row_no}: " + " / ".join(errs))

            if st.button("🔄 P1にインポート", type="primary", key="gform_import"):
                _run_bulk_import(rows)
        else:
            st.warning("CSVに取り込み可能な行が見つかりませんでした")
