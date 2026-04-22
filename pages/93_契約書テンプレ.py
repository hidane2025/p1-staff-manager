"""P1 Staff Manager — 契約書テンプレート管理

Provisional / Official の二段運用:
  - is_provisional=1 → AI生成などの仮版。PDF右上に透かし。
  - is_provisional=0 → 経理/法務レビュー済みの正規版。
"""

from __future__ import annotations

import streamlit as st

from utils import contract_db
from utils import contract_doc_parser
from utils.contract_doc_parser import (
    DocParseError,
    MissingDependencyError,
    UnsupportedFormatError,
)


st.set_page_config(page_title="契約書テンプレート", page_icon="📝", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
hide_staff_only_pages()
st.title("📝 契約書テンプレート管理")
st.caption("業務委託契約書・NDA・個人情報取扱同意書などのテンプレートを管理します。")

# ==========================================================================
# 凡例（仮版 / 正規版）
# ==========================================================================
with st.container(border=True):
    st.markdown(
        "#### 📌 仮版 / 正規版 の運用について\n"
        "- **⚠️ 仮版**（`is_provisional=1`）: AI生成 / 経理・法務レビュー前。"
        "PDF右上に赤橙の「仮版」透かしが入り、発行ログにも記録されます。\n"
        "- **✅ 正規版**（`is_provisional=0`）: 経理・法務レビュー済み。透かしなし。"
        "Word/PDF/Markdown から差し替え登録してください。"
    )


# ==========================================================================
# 新規作成（仮版として作成）
# ==========================================================================
with st.expander("➕ 新規テンプレート作成（⚠️ 仮版として登録）", expanded=False):
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
                tid = contract_db.create_template(
                    name, version, doc_type, body, is_provisional=1)
                st.success(f"✅ 仮版テンプレート作成: id={tid}")
                st.rerun()


# ==========================================================================
# 📄 正規版ファイルから新規登録
# ==========================================================================
st.divider()
st.subheader("📄 正規版ファイルから新規登録")
st.caption(
    "経理・法務レビュー済みの Word (.docx) / PDF (.pdf) / Markdown (.md) / "
    "プレーンテキスト (.txt) を取り込んで、正規版テンプレートとして登録します。"
)

uploaded = st.file_uploader(
    "正規版契約書ファイル",
    type=list(contract_doc_parser.SUPPORTED_EXTENSIONS),
    key="official_upload",
)

# 抽出結果をセッションに保持（ファイル再読込で初期化）
_UPLOAD_KEY = "_official_tpl_preview"


def _reset_preview() -> None:
    if _UPLOAD_KEY in st.session_state:
        del st.session_state[_UPLOAD_KEY]


if uploaded is not None:
    # ファイル変化を検知
    signature = (uploaded.name, uploaded.size)
    cached = st.session_state.get(_UPLOAD_KEY)
    if not cached or cached.get("sig") != signature:
        try:
            file_bytes = uploaded.getvalue()
            result = contract_doc_parser.parse_upload(uploaded.name, file_bytes)
            st.session_state[_UPLOAD_KEY] = {
                "sig": signature,
                "markdown": result.markdown,
                "parser": result.parser,
                "error": None,
                "fallback": False,
            }
        except MissingDependencyError as e:
            st.session_state[_UPLOAD_KEY] = {
                "sig": signature,
                "markdown": "",
                "parser": "",
                "error": str(e),
                "fallback": True,
            }
        except UnsupportedFormatError as e:
            st.session_state[_UPLOAD_KEY] = {
                "sig": signature,
                "markdown": "",
                "parser": "",
                "error": str(e),
                "fallback": False,
            }
        except DocParseError as e:
            st.session_state[_UPLOAD_KEY] = {
                "sig": signature,
                "markdown": "",
                "parser": "",
                "error": str(e),
                "fallback": True,
            }
        except Exception as e:  # noqa: BLE001
            st.session_state[_UPLOAD_KEY] = {
                "sig": signature,
                "markdown": "",
                "parser": "",
                "error": f"予期しないエラー: {e}",
                "fallback": True,
            }

preview = st.session_state.get(_UPLOAD_KEY)

if preview:
    if preview.get("error"):
        st.warning(f"⚠️ 自動抽出に失敗しました: {preview['error']}")
        with st.expander("🔧 技術詳細"):
            st.code(preview["error"], language=None)
        if preview.get("fallback"):
            st.info(
                "下の「手動で本文を貼り付けてください」欄にテンプレ本文を直接入力すれば、"
                "そのまま正規版として登録できます。"
            )
    else:
        st.success(
            f"✅ {preview['parser']} として抽出しました "
            f"（{len(preview['markdown']):,} 文字）"
        )

with st.form("official_template_form"):
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        off_name = st.text_input(
            "テンプレート名",
            placeholder="例：業務委託契約書（経理承認版）",
            key="off_name",
        )
    with col2:
        off_version = st.text_input("バージョン", value="v1.0", key="off_version")
    with col3:
        off_doc_type = st.selectbox(
            "種別", ["outsourcing", "nda", "privacy", "other"], key="off_doc_type")

    preview_md = preview.get("markdown", "") if preview else ""
    fallback_hint = (
        "手動で本文を貼り付けてください（Markdown 形式）"
        if preview and preview.get("fallback") else
        "抽出結果プレビュー（ここを直接編集して登録できます）"
    )
    body_md = st.text_area(
        fallback_hint,
        value=preview_md,
        height=420,
        key="off_body",
        help="{{staff_name}} {{issuer_name}} などの変数プレースホルダを含めてください。",
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        register_btn = st.form_submit_button(
            "✅ 正規版としてDBに登録", type="primary",
        )
    with c2:
        reset_btn = st.form_submit_button("↩ プレビューをクリア")

    if reset_btn:
        _reset_preview()
        st.rerun()

    if register_btn:
        if not off_name.strip():
            st.error("テンプレート名は必須です。")
        elif not body_md.strip():
            st.error("本文が空です。ファイルをアップロードするか、手動で貼り付けてください。")
        else:
            try:
                tid = contract_db.create_template(
                    off_name.strip(), off_version.strip() or "v1.0",
                    off_doc_type, body_md,
                    is_provisional=0,
                )
                st.success(f"✅ 正規版テンプレート登録: id={tid}")
                _reset_preview()
                st.rerun()
            except Exception as e:
                st.error("登録に失敗しました。")
                with st.expander("🔧 技術詳細"):
                    st.code(str(e), language=None)


# ==========================================================================
# 📋 登録済みテンプレート
# ==========================================================================
st.divider()
st.subheader("📋 登録済みテンプレート")
show_inactive = st.checkbox("無効化済みも表示", value=False)
templates = contract_db.list_templates(active_only=not show_inactive)
if not templates:
    st.info("テンプレート未登録。上部から作成してください。")
else:
    for tpl in templates:
        provisional = bool(tpl.get("is_provisional", 1))
        prov_badge = "⚠️ 仮版" if provisional else "✅ 正規版"
        active_badge = "" if tpl.get("is_active") else "🚫 無効"
        header = (
            f"{prov_badge}  #{tpl['id']}  {tpl['name']}  "
            f"({tpl['version']})  [{tpl['doc_type']}]  {active_badge}"
        ).rstrip()
        with st.expander(header, expanded=False):
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
                new_provisional = st.radio(
                    "ステータス",
                    options=[1, 0],
                    format_func=lambda x: "⚠️ 仮版（透かしあり）" if x == 1 else "✅ 正規版",
                    index=0 if provisional else 1,
                    horizontal=True,
                    key=f"prov_{tpl['id']}",
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
                        is_provisional=int(new_provisional),
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
