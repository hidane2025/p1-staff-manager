"""P1 Staff Manager — 契約書発行・管理"""

from __future__ import annotations

import streamlit as st
import pandas as pd

import db
from utils import contract_db, contract_issuer, contract_storage


st.set_page_config(page_title="契約書発行", page_icon="📄", layout="wide")
st.title("📄 契約書発行・管理")
st.caption("スタッフ向け契約書を一括発行し、署名状況を管理します。")

# ============================================================
# テンプレート選択
# ============================================================
templates = contract_db.list_templates(active_only=True)
if not templates:
    st.warning("有効なテンプレートがありません。「契約書テンプレート」ページで作成してください。")
    st.page_link("pages/C_contract_templates.py", label="テンプレート管理へ →",
                 icon="📝")
    st.stop()

tpl_options = {t["id"]: f"{t['name']} ({t['version']}) [{t['doc_type']}]"
                for t in templates}
st.subheader("① テンプレート選択")
selected_tpl_id = st.selectbox(
    "発行するテンプレート",
    options=list(tpl_options.keys()),
    format_func=lambda x: tpl_options[x],
)

# プレビュー
selected_tpl = next((t for t in templates if t["id"] == selected_tpl_id), None)
if selected_tpl:
    with st.expander("📖 テンプレート本文プレビュー"):
        st.markdown(selected_tpl["body_markdown"])

st.divider()

# ============================================================
# 大会連動 or 汎用
# ============================================================
st.subheader("② 大会連動（任意）")
events = db.get_all_events()
event_id = None
if events:
    use_event = st.checkbox("大会に連動させる", value=False)
    if use_event:
        event_id = st.selectbox(
            "連動する大会",
            options=[e["id"] for e in events],
            format_func=lambda eid: next(
                e["name"] for e in events if e["id"] == eid),
        )

st.divider()

# ============================================================
# スタッフ選択 → 一括発行
# ============================================================
st.subheader("③ 対象スタッフ選択")
client = db.get_client()
staff = client.table("p1_staff").select(
    "id, no, name_jp, real_name, email, role, employment_type"
).order("no").execute().data

if not staff:
    st.warning("スタッフが登録されていません。")
    st.stop()

df = pd.DataFrame([{
    "選択": False,
    "id": s["id"],
    "No.": s.get("no") or 0,
    "ディーラーネーム": s.get("name_jp") or "",
    "本名": s.get("real_name") or "",
    "役職": s.get("role") or "",
    "雇用区分": s.get("employment_type") or "",
    "メール": s.get("email") or "",
} for s in staff])

edited = st.data_editor(
    df,
    column_config={
        "選択": st.column_config.CheckboxColumn(required=True),
        "id": None,
    },
    disabled=["id", "No.", "ディーラーネーム", "本名", "役職", "雇用区分", "メール"],
    hide_index=True,
    use_container_width=True,
    height=400,
)

selected_ids = edited[edited["選択"] == True]["id"].tolist()
st.write(f"選択中: **{len(selected_ids)}名**")

col1, col2 = st.columns([1, 3])
with col1:
    valid_days = st.number_input("署名期限（日）", 1, 90, 14)
with col2:
    st.write("")

if st.button("📄 選択分を一括発行（未署名PDF生成→署名URL発行）",
              type="primary", disabled=(len(selected_ids) == 0)):
    with st.spinner(f"{len(selected_ids)}名分を発行中..."):
        result = contract_issuer.issue_contracts_bulk(
            selected_tpl_id, selected_ids,
            event_id=event_id, valid_days=int(valid_days),
        )
    st.success(f"発行完了: 成功 {result['success']}件 / 失敗 {result['failure']}件")
    if result["failure"] > 0:
        with st.expander("❌ 失敗詳細"):
            for r in result["results"]:
                if not r.get("ok"):
                    st.error(r.get("error"))
    st.rerun()

st.divider()

# ============================================================
# 発行済み契約一覧
# ============================================================
st.subheader("④ 発行済み契約一覧")
status_tab = st.radio(
    "ステータス絞込",
    ["全て", "未閲覧 (sent)", "閲覧済み未署名 (viewed)", "署名済み (signed)",
     "無効化 (revoked)"],
    horizontal=True,
)
status_map = {
    "全て": None,
    "未閲覧 (sent)": "sent",
    "閲覧済み未署名 (viewed)": "viewed",
    "署名済み (signed)": "signed",
    "無効化 (revoked)": "revoked",
}
contracts = contract_db.list_contracts(
    status_filter=status_map[status_tab], event_id=event_id)

if not contracts:
    st.caption("該当する契約はありません。")
else:
    from utils.url_helper import get_base_host
    base_host = get_base_host()
    rows = []
    for c in contracts:
        token = c.get("signing_token") or ""
        url = f"{base_host}/contract_sign?token={token}" if token else ""
        icon = {
            "draft": "📝", "sent": "📧",
            "viewed": "👀", "signed": "✅",
            "revoked": "🚫", "expired": "⏰",
        }.get(c["status"], "❓")
        rows.append({
            "ID": c["id"],
            "No.": c["contract_no"],
            "テンプレ": c.get("template_name") or "",
            "スタッフ": f"{c.get('staff_name_jp')} ({c.get('staff_real_name')})",
            "ステータス": f"{icon} {c['status']}",
            "閲覧数": c.get("view_count") or 0,
            "署名日時": c.get("signed_at") or "",
            "署名URL": url,
        })
    df_contracts = pd.DataFrame(rows)
    st.dataframe(
        df_contracts,
        column_config={
            "署名URL": st.column_config.LinkColumn(display_text="🔗 コピー"),
        },
        hide_index=True,
        use_container_width=True,
    )

    # CSV出力
    csv = df_contracts.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 署名URL一覧CSV",
        data=csv,
        file_name="contract_signing_urls.csv",
        mime="text/csv",
    )

    # 署名済みPDFダウンロード（個別）
    with st.expander("📑 署名済みPDFダウンロード"):
        signed_contracts = [c for c in contracts if c["status"] == "signed"]
        if not signed_contracts:
            st.caption("署名済み契約はありません。")
        else:
            for c in signed_contracts:
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.text(f"{c['contract_no']} — {c.get('staff_name_jp')}")
                with col_b:
                    signed_path = c.get("signed_pdf_path")
                    if signed_path:
                        pdf_b = contract_storage.download_bytes(signed_path)
                        if pdf_b:
                            st.download_button(
                                "📥 DL",
                                data=pdf_b,
                                file_name=f"{c['contract_no']}_signed.pdf",
                                mime="application/pdf",
                                key=f"dl_{c['id']}",
                            )
