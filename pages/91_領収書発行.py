"""P1 Staff Manager — 領収書発行管理（管理者向け）"""

from __future__ import annotations

import streamlit as st
import pandas as pd

import db
from utils import receipt_db
from utils import receipt_issuer
from utils import event_selector


st.set_page_config(page_title="領収書発行", page_icon="📄", layout="wide")
st.title("📄 領収書発行")
st.caption("支払確定分の領収書をPDF生成し、スタッフ用DLリンクを発行します。")

# --- イベント選択 ---
events = db.get_all_events()
if not events:
    st.warning("イベントが登録されていません。先に『イベント作成』ページで登録してください。")
    st.stop()

event_id = event_selector.select_event(events, label="対象イベント")
if not event_id:
    st.stop()

st.divider()

# --- 発行者情報の状態表示 ---
issuer = receipt_db.get_issuer_settings(event_id)
with st.expander("📝 発行者情報（現在の設定）", expanded=False):
    col1, col2 = st.columns(2)
    with col1:
        st.text(f"発行者名: {issuer['issuer_name']}")
        st.text(f"住所: {issuer['issuer_address'] or '(未設定)'}")
        st.text(f"電話: {issuer['issuer_tel'] or '(未設定)'}")
    with col2:
        inv = issuer["invoice_number"] or "(未登録・後日追加可)"
        st.text(f"インボイス番号: {inv}")
        st.text(f"但し書き: {issuer['receipt_purpose']}")
        st.text(f"電子印影: {'✅ 設定済み' if issuer['issuer_seal_url'] else '(未設定)'}")
    st.info("編集は『発行者設定』ページから行ってください。")

st.divider()

# --- 発行対象一覧 ---
status_filter = st.radio(
    "発行対象",
    ["承認/支払済みのみ (推奨)", "未発行のみ", "すべて"],
    horizontal=True,
)
filter_key = {
    "承認/支払済みのみ (推奨)": "approved_or_paid",
    "未発行のみ": "unissued",
    "すべて": "all",
}[status_filter]

rows = receipt_db.get_payments_needing_receipt(event_id, filter_key)

if not rows:
    st.info("対象となる支払がありません。")
    st.stop()

# 表示
display_rows = []
for r in rows:
    status_jp = {
        "pending": "未承認",
        "approved": "承認済み",
        "paid": "支払済み",
    }.get(r.get("status") or "pending", "不明")
    display_rows.append({
        "選択": False,
        "id": r["id"],
        "No.": r.get("no", 0),
        "ディーラーネーム": r.get("name_jp", ""),
        "本名": r.get("real_name", ""),
        "金額": r.get("total_amount", 0),
        "ステータス": status_jp,
        "領収書": "✅ 発行済み" if r.get("receipt_pdf_path") else "未発行",
        "DL回数": r.get("receipt_download_count") or 0,
    })
df = pd.DataFrame(display_rows)

st.markdown(f"**対象 {len(df)}件**")
edited = st.data_editor(
    df,
    column_config={
        "選択": st.column_config.CheckboxColumn(required=True),
        "金額": st.column_config.NumberColumn(format="¥%d"),
        "id": None,  # 非表示
    },
    disabled=["id", "No.", "ディーラーネーム", "本名",
              "金額", "ステータス", "領収書", "DL回数"],
    hide_index=True,
    use_container_width=True,
)

selected = edited[edited["選択"] == True]
selected_ids: list[int] = selected["id"].tolist()

col1, col2, col3 = st.columns([2, 2, 3])
with col1:
    valid_days = st.number_input("DLリンク有効期限（日）", min_value=1,
                                   max_value=90, value=7)
with col2:
    force = st.checkbox("強制再生成（既存を上書き）", value=False)

st.write(f"選択中: **{len(selected_ids)}名**")

if st.button("📄 選択分を一括発行", type="primary", disabled=(len(selected_ids) == 0)):
    with st.spinner(f"{len(selected_ids)}名分を発行中..."):
        result = receipt_issuer.issue_receipts_bulk(
            selected_ids, valid_days=int(valid_days), force_regenerate=force
        )
    st.success(f"発行完了: 成功 {result['success']}件 / 失敗 {result['failure']}件")
    if result["failure"] > 0:
        with st.expander("❌ 失敗詳細"):
            for r in result["results"]:
                if not r.get("ok"):
                    st.error(f"payment_id={r.get('payment_id')}: {r.get('error')}")
    st.rerun()

# --- DLリンク一覧 ---
st.divider()
st.subheader("🔗 発行済み領収書のDLリンク")

issued = [r for r in rows if r.get("receipt_pdf_path") and r.get("receipt_token")]
if not issued:
    st.caption("発行済みの領収書はまだありません。")
else:
    # 公開URLのベースは自動判定（secrets override → Hostヘッダ → fallback）
    from utils.url_helper import get_base_host
    base_host = get_base_host()

    table_rows = []
    for r in issued:
        token = r["receipt_token"]
        url = f"{base_host}/9_receipt_download?token={token}"
        table_rows.append({
            "No.": r.get("no", 0),
            "ディーラーネーム": r.get("name_jp", ""),
            "本名": r.get("real_name", ""),
            "金額": r.get("total_amount", 0),
            "DL回数": r.get("receipt_download_count") or 0,
            "有効期限": r.get("receipt_token_expires_at") or "",
            "DLリンク": url,
        })
    df_links = pd.DataFrame(table_rows)
    st.dataframe(
        df_links,
        column_config={
            "金額": st.column_config.NumberColumn(format="¥%d"),
            "DLリンク": st.column_config.LinkColumn("DLリンク", display_text="🔗 コピー用"),
        },
        hide_index=True,
        use_container_width=True,
    )

    # CSV出力（LINE等に貼り付け配布用）
    csv = df_links.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 DLリンク一覧をCSVでダウンロード",
        data=csv,
        file_name=f"receipt_links_event{event_id}.csv",
        mime="text/csv",
    )
