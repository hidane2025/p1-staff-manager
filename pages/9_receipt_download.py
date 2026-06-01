"""P1 Staff Manager — 領収書DLページ（スタッフ向け・公開）

URL: /?token=xxxx でアクセス
トークンを検証して期限内なら領収書PDFをダウンロード可能にする。
"""

import streamlit as st

import db
from utils import receipt_db
from utils import receipt_storage
from utils import receipt_token


st.set_page_config(
    page_title="領収書ダウンロード",
    page_icon="📄",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# サイドバー非表示CSS（スタッフに管理画面メニューを見せない）
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
# スタッフ向け公開ページ。サイドバーは隠す＋管理ページのクイックナビも出さない。
apply_global_style(show_quicknav=False)
st.title("📄 領収書ダウンロード")

query_params = st.query_params
token = query_params.get("token", "")

if not token:
    st.warning("URLが不正です。受け取ったリンクから再度アクセスしてください。")
    st.stop()

# トークン検証
record = receipt_db.find_payment_by_token(token)
if not record:
    st.error("このリンクは無効です。発行者（Pacific）にお問い合わせください。")
    st.stop()

if receipt_token.is_expired(record.get("receipt_token_expires_at")):
    st.error("このリンクは期限切れです。発行者（Pacific）に再発行を依頼してください。")
    st.stop()

pdf_path = record.get("receipt_pdf_path")
if not pdf_path:
    st.error("領収書がまだ準備できていません。発行者にお問い合わせください。")
    st.stop()

# PDF取得
pdf_bytes = receipt_storage.download_pdf(pdf_path)
if not pdf_bytes:
    st.error("領収書ファイルを取得できませんでした。お手数ですが発行者にお問い合わせください。")
    st.stop()

receipt_no = record.get("receipt_no") or "receipt"
# A-6: 表示額は確定額(payable_amount)＝PDFの額面・封筒の現金と一致させる
amount = db.get_payable(record)

# C-1: 証憑アクセスの監査ログ。トークン保持者が本名・住所入りPDFを取得した記録を残す。
# （発行側は記録するのに DL 側が無記録だった非対称を解消）。
# Streamlit のリラン多発を避けるため、同一トークンはセッション内で1回だけ記録する。
# PII（本名・住所・金額）はログ detail に含めない（receipt_no のみ）。
_access_logged_key = f"_receipt_access_logged_{token[:12]}"
if not st.session_state.get(_access_logged_key):
    try:
        import db as _db
        _ua = ""
        try:
            _hdrs = getattr(st.context, "headers", {}) or {}
            _ua = (_hdrs.get("User-Agent") or "")[:80]
        except Exception:
            _ua = ""
        _db.log_action(
            "access_receipt", "payments", record["id"],
            detail=f"receipt_no={receipt_no} / トークン経由閲覧 / UA={_ua}",
            event_id=record.get("event_id"),
            performed_by="receipt_link",
        )
    except Exception:
        pass
    st.session_state[_access_logged_key] = True

st.success("✅ 領収書の準備ができました")
st.metric("領収金額", f"¥{amount:,}")
st.caption(f"領収書No: {receipt_no}")

if st.download_button(
    label="📥 PDFをダウンロード",
    data=pdf_bytes,
    file_name=f"{receipt_no}.pdf",
    mime="application/pdf",
    use_container_width=True,
    type="primary",
):
    try:
        receipt_db.mark_receipt_downloaded(record["id"])
    except Exception:
        pass

dl_count = record.get("receipt_download_count") or 0
if dl_count > 0:
    st.caption(f"これまでのダウンロード回数: {dl_count}回")

st.divider()
st.caption(
    "※ この領収書は電子的に発行されたものです。収入印紙の貼付は不要です。\n"
    "※ 内容に相違がある場合は、発行者（Pacific）までご連絡ください。"
)
