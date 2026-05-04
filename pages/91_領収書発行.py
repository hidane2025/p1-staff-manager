"""P1 Staff Manager — 領収書発行管理（管理者向け）"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

import streamlit as st
import pandas as pd

import db
from utils import receipt_db
from utils import receipt_issuer
from utils import receipt_storage
from utils import event_selector


st.set_page_config(page_title="領収書発行", page_icon="📄", layout="wide")
from utils.ui_helpers import hide_staff_only_pages, missing_field_warning, copyable_url
from utils.page_layout import apply_global_style, page_header, flow_bar
from utils.admin_guard import require_admin, admin_logout_button, operator_name
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="領収書発行")
admin_logout_button()

page_header("📄 領収書発行", "支払確定分の領収書を PDF 生成し、スタッフ向けの個別 DL URL を発行します。")
flow_bar(active="payout", done=["setup", "input", "calc"])

# PII閲覧監査ログ
db.log_action("view_receipts_admin", "payments",
              detail=f"page=領収書発行", performed_by=operator_name())

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
        st.text(f"税額内訳表示: {'✅ ON' if issuer.get('show_tax_breakdown') else 'OFF'}")
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

# 選択されたスタッフの本名・住所欠損をチェック
selected_rows_data = [r for r in rows if r["id"] in selected_ids]
if selected_rows_data:
    missing_list = missing_field_warning(selected_rows_data, ["real_name"])
    if missing_list:
        proceed = st.checkbox(
            "⚠️ 本名未登録でも発行する（領収書の宛名はディーラーネームになります）",
            value=False,
        )
    else:
        proceed = True
else:
    proceed = False

if st.button("📄 選択分を一括発行", type="primary",
             disabled=(len(selected_ids) == 0 or not proceed)):
    try:
        with st.spinner(f"{len(selected_ids)}名分を発行中..."):
            result = receipt_issuer.issue_receipts_bulk(
                selected_ids, valid_days=int(valid_days), force_regenerate=force
            )
        st.success(f"✅ 発行完了: 成功 {result['success']}件 / 失敗 {result['failure']}件")
        if result["failure"] > 0:
            with st.expander("❌ 失敗詳細"):
                for r in result["results"]:
                    if not r.get("ok"):
                        st.error(f"payment_id={r.get('payment_id')}: {r.get('error')}")
        st.rerun()
    except Exception as e:
        st.error("💥 発行処理中にエラーが発生しました。ネットワーク状況を確認して再度お試しください。")
        with st.expander("🔧 技術詳細（管理者向け）"):
            st.code(str(e), language=None)

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
        url = f"{base_host}/receipt_download?token={token}"
        table_rows.append({
            "No.": r.get("no", 0),
            "ディーラーネーム": r.get("name_jp", ""),
            "本名": r.get("real_name", ""),
            "金額": r.get("total_amount", 0),
            "DL回数": r.get("receipt_download_count") or 0,
            "有効期限": r.get("receipt_token_expires_at") or "",
            "URL": url,
        })
    df_links = pd.DataFrame(table_rows)
    st.dataframe(
        df_links,
        column_config={
            "金額": st.column_config.NumberColumn(format="¥%d"),
        },
        hide_index=True,
        use_container_width=True,
    )

    # --- 個別URLコピー（1クリックでクリップボード） ---
    st.markdown("#### 📋 URLをコピー（LINE等に貼り付け用）")
    st.caption("下記コードブロック右上のコピーアイコンを押すと、URLがクリップボードに入ります。")

    # モード選択
    copy_mode = st.radio(
        "表示形式",
        ["個別（1名ずつ）", "一括（全員分まとめて）"],
        horizontal=True,
    )

    if copy_mode == "個別（1名ずつ）":
        staff_choices = {
            f"{r['No.']} {r['ディーラーネーム']}（{r['本名']}） ¥{r['金額']:,}": r["URL"]
            for r in table_rows
        }
        picked = st.selectbox("スタッフ選択", list(staff_choices.keys()))
        copyable_url(staff_choices[picked], label="このスタッフのDL URL")
    else:
        # 全員分を LINE送信風にまとめる
        bulk_text = "\n\n".join(
            f"{r['本名'] or r['ディーラーネーム']}さん\n{r['URL']}"
            for r in table_rows
        )
        copyable_url(bulk_text, label="全員分まとめて（LINE等にコピー&ペースト）")

    # CSV出力
    st.markdown("---")
    csv = df_links.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 DLリンク一覧をCSVでダウンロード",
        data=csv,
        file_name=f"receipt_links_event{event_id}.csv",
        mime="text/csv",
    )

    # --- 原本ZIP一括DL（Pacific保管用） ---
    st.markdown("---")
    st.subheader("📦 原本ZIPを一括ダウンロード")
    st.caption(
        "発行者（Pacific）保管用として、全員分の「原本」PDFをまとめてZIPで取得します。"
        "経理保管・税務対応にお使いください。"
    )

    # 原本パスを持っている領収書のみを対象とする
    # （旧仕様で発行された領収書は receipt_original_path が空の可能性あり）
    original_ready = [r for r in issued if r.get("receipt_original_path")]
    original_missing = len(issued) - len(original_ready)

    if original_missing > 0:
        st.warning(
            f"⚠️ 原本PDFが未生成の領収書が {original_missing} 件あります。"
            "これらは旧バージョンで発行されたため、『強制再生成』で原本を作り直してください。"
        )

    if not original_ready:
        st.caption("原本PDFが生成済みの領収書がまだありません。")
    else:
        if st.button(
            f"📦 原本ZIPを作成・ダウンロード ({len(original_ready)}件)",
            type="primary",
        ):
            try:
                with st.spinner(f"{len(original_ready)}件の原本PDFをZIP化中..."):
                    zip_buf = io.BytesIO()
                    errors: list[str] = []
                    with zipfile.ZipFile(
                        zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED
                    ) as zf:
                        for r in original_ready:
                            original_path = r.get("receipt_original_path")
                            receipt_no = r.get("receipt_no") or f"unknown_{r['id']}"
                            if not original_path:
                                continue
                            pdf_bytes = receipt_storage.download_pdf(original_path)
                            if not pdf_bytes:
                                errors.append(f"No.{receipt_no}: ダウンロード失敗")
                                continue
                            # ZIP内ファイル名: {receipt_no}_原本.pdf
                            zf.writestr(f"{receipt_no}_原本.pdf", pdf_bytes)
                    zip_buf.seek(0)

                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    "📥 ZIPをダウンロード",
                    data=zip_buf.getvalue(),
                    file_name=f"receipts_original_event{event_id}_{stamp}.zip",
                    mime="application/zip",
                )
                if errors:
                    st.warning(
                        f"一部ファイルの取得に失敗しました ({len(errors)}件)："
                    )
                    for msg in errors:
                        st.caption(f"- {msg}")
                else:
                    st.success(f"✅ {len(original_ready)}件の原本PDFをZIP化しました。")
            except Exception as e:
                st.error("💥 ZIP生成中にエラーが発生しました。")
                with st.expander("🔧 技術詳細（管理者向け）"):
                    st.code(str(e), language=None)
