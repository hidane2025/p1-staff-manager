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
apply_global_style()
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
    st.success("✅ この契約書はすでに署名済みです。")
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
st.caption("以下の内容を必ずご確認の上、電子署名してください。")

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

# ---- 同意チェックと署名 ----
st.subheader("📝 署名")
agree = st.checkbox(
    "上記の契約内容を確認しました。本電子署名をもって、契約締結の意思表示とします。",
    value=False,
)

# ---- 署名パッド ----
try:
    from streamlit_drawable_canvas import st_canvas

    st.caption("以下の枠内にマウスまたは指で署名してください。")
    canvas_result = st_canvas(
        fill_color="rgba(255, 255, 255, 0)",
        stroke_width=3,
        stroke_color="#000000",
        background_color="#FFFFFF",
        height=200,
        width=550,
        drawing_mode="freedraw",
        key="signature_canvas",
    )
    sig_image_array = canvas_result.image_data
    has_canvas = True
except ImportError:
    st.warning("電子署名パッドが利用できません。代わりに署名画像（PNG）をアップロードしてください。")
    has_canvas = False
    uploaded = st.file_uploader("署名画像（PNG推奨）", type=["png", "jpg", "jpeg"])
    sig_image_array = None

# Ultra Review M-4対策: 二重送信ガード
# 送信中フラグ・送信済みフラグをsession_stateで管理
SUBMIT_LOCK_KEY = f"signing_{contract['id']}"
if SUBMIT_LOCK_KEY not in st.session_state:
    st.session_state[SUBMIT_LOCK_KEY] = "idle"  # idle/submitting/done

submit_state = st.session_state[SUBMIT_LOCK_KEY]

col_a, col_b = st.columns([1, 1])
with col_a:
    clear = st.button(
        "🗑 署名をやり直す",
        use_container_width=True,
        disabled=(submit_state != "idle"),
    )
    if clear and has_canvas:
        st.rerun()

with col_b:
    submit_label = {
        "idle": "✅ 署名して送信",
        "submitting": "⏳ 送信中... お待ちください",
        "done": "✅ 送信完了",
    }[submit_state]
    submit = st.button(
        submit_label,
        type="primary",
        disabled=(not agree or submit_state != "idle"),
        use_container_width=True,
    )

if submit:
    # Ultra Review M-4対策: submitting 状態にロック
    st.session_state[SUBMIT_LOCK_KEY] = "submitting"
    sig_png_bytes = None

    if has_canvas and sig_image_array is not None:
        # numpy配列→PNG
        try:
            img = Image.fromarray(sig_image_array.astype("uint8"))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            sig_png_bytes = buf.getvalue()
        except Exception as e:
            st.error(f"署名画像の変換に失敗: {e}")
    elif not has_canvas and 'uploaded' in locals() and uploaded:
        sig_png_bytes = uploaded.read()

    if not sig_png_bytes:
        st.session_state[SUBMIT_LOCK_KEY] = "idle"  # rollback
        st.error("署名を描画してください。")
    else:
        # 空白チェック（全部白なら拒否）
        try:
            img_check = Image.open(io.BytesIO(sig_png_bytes)).convert("RGB")
            extrema = img_check.getextrema()
            is_all_white = all(e[0] >= 250 and e[1] >= 250 for e in extrema)
            if is_all_white:
                st.session_state[SUBMIT_LOCK_KEY] = "idle"  # rollback
                st.error("署名が空白です。描画してから再度送信してください。")
                st.stop()
        except Exception:
            pass

        with st.spinner("署名処理中..."):
            # IPアドレスとUAは取得難しい（Streamlit Cloud上）→ 空で記録
            result = contract_issuer.apply_signature(
                contract["id"], sig_png_bytes,
                signer_ip="", signer_ua="",
            )
        if result["ok"]:
            st.session_state[SUBMIT_LOCK_KEY] = "done"
            st.success("✅ 署名が完了しました。ありがとうございます。")
            st.caption(f"契約書No: {contract['contract_no']}")
            st.caption(f"Content-Hash (SHA-256先頭16): {result['content_hash'][:16]}")
            signed_pdf = contract_storage.download_bytes(result["signed_pdf_path"])
            if signed_pdf:
                st.download_button(
                    "📥 署名済みPDFをダウンロード",
                    data=signed_pdf,
                    file_name=f"{contract['contract_no']}_signed.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )
            st.info("署名完了の記録がサーバーに保存されました。上記PDFは控えとして保管してください。")
        else:
            # 失敗時はロックを戻す（リトライ可能に）
            st.session_state[SUBMIT_LOCK_KEY] = "idle"
            st.error(f"署名処理に失敗しました: {result.get('error')}")

st.divider()
st.caption(
    "※ 本電子署名は電子署名法第2条に基づく有効な署名として扱われます。"
    "改ざん防止のため、署名日時とSHA-256ハッシュがPDFに記録されます。"
)
