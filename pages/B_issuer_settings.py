"""P1 Staff Manager — 発行者設定（領収書/契約書用）"""

from __future__ import annotations

import streamlit as st

import db
from utils import receipt_db
from utils import event_selector


st.set_page_config(page_title="発行者設定", page_icon="🏢", layout="wide")
st.title("🏢 発行者設定")
st.caption("領収書PDFに記載する発行者（Pacific）情報を設定します。インボイス番号は後日追加可能です。")

events = db.get_all_events()
if not events:
    st.warning("イベントを先に作成してください。")
    st.stop()

event_id = event_selector.select_event(events, label="対象イベント")
if not event_id:
    st.stop()

st.divider()

cur = receipt_db.get_issuer_settings(event_id)

with st.form("issuer_form"):
    col1, col2 = st.columns(2)
    with col1:
        issuer_name = st.text_input("発行者名 *", value=cur["issuer_name"],
                                      help="例: 株式会社パシフィック")
        issuer_address = st.text_area("発行者住所", value=cur["issuer_address"],
                                        height=70)
        issuer_tel = st.text_input("電話番号", value=cur["issuer_tel"])
    with col2:
        receipt_purpose = st.text_input(
            "但し書き（デフォルト）",
            value=cur["receipt_purpose"],
            help="例: ポーカー大会運営業務委託費として",
        )
        invoice_number = st.text_input(
            "適格請求書発行事業者登録番号（インボイス番号）",
            value=cur["invoice_number"],
            placeholder="T1234567890123（未登録なら空欄のまま）",
            help="空欄の場合、領収書には印字されません。後日登録した際にここに入力するだけで自動反映します。",
        )
        issuer_seal_url = st.text_input(
            "電子印影URL（任意）",
            value=cur["issuer_seal_url"],
            help="PNG推奨。Supabase Storageの受付URL or 外部URL。空欄で印影なし。",
        )

    submitted = st.form_submit_button("💾 保存", type="primary")
    if submitted:
        receipt_db.save_issuer_settings(
            event_id,
            issuer_name=issuer_name,
            issuer_address=issuer_address,
            issuer_tel=issuer_tel,
            invoice_number=invoice_number,
            issuer_seal_url=issuer_seal_url,
            receipt_purpose=receipt_purpose,
        )
        st.success("✅ 発行者情報を保存しました")
        st.rerun()

st.divider()
st.markdown("""
### 📝 運用メモ

- **インボイス番号**は空欄のままで運用可能です。後日Pacificが適格請求書発行事業者として登録された時に、この画面で入力するだけで全ての領収書に自動反映されます。
- **電子印影**はPNG推奨。背景透過で150×150px程度。
- **発行者情報はイベント単位**で設定できます。新しい大会で発行者が変わる場合はイベントごとに更新してください。
- **過去に発行済みの領収書は再生成が必要**です（領収書発行ページの『強制再生成』を使ってください）。
""")
