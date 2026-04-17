"""P1 Staff Manager — 契約書テンプレート管理"""

from __future__ import annotations

import streamlit as st

from utils import contract_db


st.set_page_config(page_title="契約書テンプレート", page_icon="📝", layout="wide")
st.title("📝 契約書テンプレート管理")
st.caption("業務委託契約書・NDA・個人情報取扱同意書などのテンプレートを管理します。")

# 新規作成エリア
with st.expander("➕ 新規テンプレート作成", expanded=False):
    with st.form("new_template"):
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            name = st.text_input("テンプレート名", placeholder="例：業務委託契約書")
        with col2:
            version = st.text_input("バージョン", value="v1.0")
        with col3:
            doc_type = st.selectbox("種別", ["outsourcing", "nda", "privacy", "other"])
        body = st.text_area(
            "本文（Markdown・{{変数}}対応）",
            height=400,
            placeholder="# 業務委託契約書\n\n{{issuer_name}}（以下「甲」という）と、{{staff_name}}...",
            help="利用可能な変数: {{staff_name}} {{staff_address}} {{staff_email}} {{role}} "
                  "{{event_name}} {{issuer_name}} {{issuer_address}} {{issue_date}}"
        )
        submitted = st.form_submit_button("作成", type="primary")
        if submitted:
            if not name or not body:
                st.error("名前と本文は必須です")
            else:
                tid = contract_db.create_template(name, version, doc_type, body)
                st.success(f"✅ テンプレート作成: id={tid}")
                st.rerun()

# 一覧表示
st.divider()
st.subheader("📋 登録済みテンプレート")
show_inactive = st.checkbox("無効化済みも表示", value=False)
templates = contract_db.list_templates(active_only=not show_inactive)
if not templates:
    st.info("テンプレート未登録。上部から作成してください。")
else:
    for tpl in templates:
        with st.expander(
            f"#{tpl['id']}  {tpl['name']}  ({tpl['version']})  "
            f"[{tpl['doc_type']}]  {'✅' if tpl.get('is_active') else '🚫 無効'}",
            expanded=False,
        ):
            col_a, col_b = st.columns([3, 1])
            with col_a:
                new_name = st.text_input(
                    "名前", value=tpl["name"], key=f"name_{tpl['id']}")
                new_version = st.text_input(
                    "バージョン", value=tpl["version"], key=f"ver_{tpl['id']}")
                new_type = st.selectbox(
                    "種別",
                    ["outsourcing", "nda", "privacy", "other"],
                    index=["outsourcing", "nda", "privacy", "other"].index(
                        tpl.get("doc_type") or "outsourcing"),
                    key=f"type_{tpl['id']}",
                )
                new_body = st.text_area(
                    "本文",
                    value=tpl.get("body_markdown") or "",
                    height=300,
                    key=f"body_{tpl['id']}",
                )
            with col_b:
                st.markdown("**操作**")
                if st.button("💾 保存", key=f"save_{tpl['id']}",
                              type="primary"):
                    contract_db.update_template(
                        tpl["id"],
                        name=new_name, version=new_version,
                        doc_type=new_type, body_markdown=new_body,
                    )
                    st.success("保存しました")
                    st.rerun()
                if tpl.get("is_active"):
                    if st.button("🚫 無効化", key=f"deact_{tpl['id']}"):
                        contract_db.deactivate_template(tpl["id"])
                        st.rerun()
                else:
                    if st.button("✅ 有効化", key=f"act_{tpl['id']}"):
                        contract_db.update_template(tpl["id"], is_active=1)
                        st.rerun()

st.divider()
st.caption("""
**変数リファレンス**
- `{{staff_name}}` — スタッフ本名
- `{{staff_address}}` — スタッフ住所
- `{{staff_email}}` — スタッフメール
- `{{role}}` — 役職
- `{{event_name}}` — 大会名（大会連動契約の場合）
- `{{issuer_name}}` — 発行者名（Pacific）
- `{{issuer_address}}` — 発行者住所
- `{{issue_date}}` — 発行日（自動）
- `{{confidentiality_years}}` — NDAの秘密保持期間（年）
""")
