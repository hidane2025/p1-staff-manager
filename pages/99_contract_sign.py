"""P1 Staff Manager — スタッフ用契約書署名ページ

URL: /?token=xxxx でアクセス
トークン検証 → 契約内容確認 → 電子署名パッドで署名 → 送信
"""

from __future__ import annotations

import io
import json

import streamlit as st
from PIL import Image

from utils import contract_db, contract_issuer, contract_storage
from utils import receipt_token


st.set_page_config(
    page_title="契約書 電子署名",
    page_icon="✍",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# サイドバー非表示
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { display: none; }
    [data-testid="collapsedControl"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

from utils.page_layout import apply_global_style
# スタッフ向け公開ページ。管理ページのクイックナビは出さない。
apply_global_style(show_quicknav=False)
st.title("✍ 契約書 電子署名")

# ---- トークン検証 ----
token = st.query_params.get("token", "")
if not token:
    st.warning("URLが不正です。受け取ったリンクから再度アクセスしてください。")
    st.stop()

contract = contract_db.find_contract_by_token(token)
if not contract:
    st.error("このリンクは無効です。発行者にお問い合わせください。")
    st.stop()

if receipt_token.is_expired(contract.get("signing_token_expires_at")):
    st.error("このリンクは期限切れです。発行者に再発行を依頼してください。")
    st.stop()

if contract["status"] == "revoked":
    st.error("この契約は無効化されています。")
    st.stop()

# 閲覧マーク
if contract["status"] in ("sent", "viewed"):
    contract_db.mark_viewed(contract["id"])

# ---- 既に署名済みの場合 ----
if contract["status"] == "signed":
    st.success("✅ この契約書はすでに締結済みです。")
    signed_path = contract.get("signed_pdf_path")
    if signed_path:
        pdf_b = contract_storage.download_bytes(signed_path)
        if pdf_b:
            st.download_button(
                "📥 署名済みPDFをダウンロード",
                data=pdf_b,
                file_name=f"{contract['contract_no']}_signed.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
    st.caption(f"署名日時: {contract.get('signed_at') or '-'}")
    st.stop()

# ---- 契約内容表示 ----
# Ultra Review CR-1対策: 発行時スナップショット(rendered_body_md)を最優先で使う。
# 旧契約で未記録の場合のみテンプレートから再生成。
rendered = contract.get("rendered_body_md")
if not rendered:
    tpl = contract_db.get_template(contract["template_id"])
    if not tpl:
        st.error("テンプレートが見つかりません。発行者にお問い合わせください。")
        st.stop()
    variables = json.loads(contract.get("variables_json") or "{}")
    rendered = tpl["body_markdown"]
    for k, v in variables.items():
        rendered = rendered.replace(f"{{{{{k}}}}}", v or "")

st.info(f"契約書No: **{contract['contract_no']}**")
st.caption("以下の内容を必ずご確認ください。")

with st.container(border=True):
    st.markdown(rendered)

# ---- 未署名PDFのDLも提供 ----
unsigned_path = contract.get("unsigned_pdf_path")
if unsigned_path:
    pdf_u = contract_storage.download_bytes(unsigned_path)
    if pdf_u:
        st.download_button(
            "📄 PDFで内容を確認（任意）",
            data=pdf_u,
            file_name=f"{contract['contract_no']}_確認用.pdf",
            mime="application/pdf",
        )

st.divider()

# ---- 同意チェックと締結（クリック同意方式・2026-07-10 署名パッド廃止） ----
st.subheader("📝 契約への同意")
agree = st.checkbox(
    "上記の契約内容を確認しました。「同意して契約を締結する」の押下をもって、契約締結の意思表示とします。",
    value=False,
)

# 二重送信ガード（Ultra Review M-4 の方式を踏襲）
SUBMIT_LOCK_KEY = f"signing_{contract['id']}"
if SUBMIT_LOCK_KEY not in st.session_state:
    st.session_state[SUBMIT_LOCK_KEY] = "idle"  # idle/submitting/done

submit_state = st.session_state[SUBMIT_LOCK_KEY]
submit_label = {
    "idle": "✅ 同意して契約を締結する",
    "submitting": "⏳ 処理中... お待ちください",
    "done": "✅ 締結完了",
}[submit_state]
submit = st.button(
    submit_label,
    type="primary",
    disabled=(not agree or submit_state != "idle"),
    use_container_width=True,
)
if not agree and submit_state == "idle":
    st.caption("↑ 内容を確認のうえチェックを入れると、締結ボタンが押せるようになります。")

if submit:
    st.session_state[SUBMIT_LOCK_KEY] = "submitting"
    with st.spinner("契約を締結しています..."):
        # IPはStreamlit Cloud上で取得不可のため空。UAはブラウザ由来のcontextから取得を試みる。
        try:
            _ua = st.context.headers.get("User-Agent", "")
        except Exception:
            _ua = ""
        result = contract_issuer.apply_click_agreement(
            contract["id"], signer_ip="", signer_ua=_ua,
        )
    if result["ok"]:
        st.session_state[SUBMIT_LOCK_KEY] = "done"
        st.success("✅ 契約が締結されました。ありがとうございます。")
        st.caption(f"契約書No: {contract['contract_no']}")
        st.caption(f"同意日時: {result['signed_at']}")
        st.caption(f"Content-Hash (SHA-256先頭16): {result['content_hash'][:16]}")
        signed_pdf = contract_storage.download_bytes(result["signed_pdf_path"])
        if signed_pdf:
            st.download_button(
                "📥 締結済みPDFをダウンロード",
                data=signed_pdf,
                file_name=f"{contract['contract_no']}_締結済み.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
        st.info("締結の記録がサーバーに保存されました。上記PDFは控えとして保管してください。")
    else:
        st.session_state[SUBMIT_LOCK_KEY] = "idle"
        st.error(f"締結処理に失敗しました: {result.get('error')}")

st.divider()
st.caption(
    "※ 本同意は電子契約として日時・内容ハッシュとともに記録され、書面の契約と同等の効力を有します。"
    "改ざん防止のため、署名日時とSHA-256ハッシュがPDFに記録されます。"
)
