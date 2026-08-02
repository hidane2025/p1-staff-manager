"""P1 Staff Manager — 契約書発行・管理"""

from __future__ import annotations

import streamlit as st
import pandas as pd

import db
from utils import contract_db, contract_issuer, contract_storage


st.set_page_config(page_title="契約書発行", page_icon="✍️", layout="wide")
from utils.ui_helpers import hide_staff_only_pages, missing_field_warning, copyable_url
from utils.page_layout import apply_global_style, page_header, flow_bar
from utils.admin_guard import require_admin, admin_logout_button, operator_name
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="契約書発行")
admin_logout_button()

page_header("✍️ 契約書発行・管理", "スタッフ向け契約書を一括発行し、クラウド署名状況を一覧で管理します。")
flow_bar(active="payout", done=["setup", "input", "calc"])

# PII閲覧監査ログ
db.log_action("view_contracts_admin", "contracts",
              detail=f"page=契約書発行", performed_by=operator_name())

# ============================================================
# テンプレート選択
# ============================================================
templates = contract_db.list_templates(active_only=True)
if not templates:
    st.warning("有効なテンプレートがありません。「契約書テンプレート」ページで作成してください。")
    st.page_link("pages/93_contract_template.py", label="テンプレート管理へ →",
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

# 本名・住所欠損チェック
selected_rows_data = [s for s in staff if s["id"] in selected_ids]
if selected_rows_data:
    # staff dict の shape に合わせて missing_field_warning を呼ぶ
    _norm = [{"no": s.get("no"), "name_jp": s.get("name_jp"),
              "real_name": s.get("real_name"), "address": ""}
             for s in selected_rows_data]
    missing_list = missing_field_warning(
        _norm,
        ["real_name"],
        warning_text=(
            "このまま発行すると、契約書の乙名義がディーラーネーム"
            "（本名でなくニックネーム）になります。"
        ),
    )
    if missing_list:
        proceed = st.checkbox(
            "⚠️ 本名未登録でも発行する（契約書の乙名義はディーラーネームになります）",
            value=False,
        )
    else:
        proceed = True
else:
    proceed = False

col1, col2 = st.columns([1, 3])
with col1:
    valid_days = st.number_input("署名期限（日）", 1, 90, 14)
with col2:
    st.write("")

if st.button("📄 選択分を一括発行（未署名PDF生成→署名URL発行）",
              type="primary", disabled=(len(selected_ids) == 0 or not proceed)):
    try:
        with st.spinner(f"{len(selected_ids)}名分を発行中..."):
            result = contract_issuer.issue_contracts_bulk(
                selected_tpl_id, selected_ids,
                event_id=event_id, valid_days=int(valid_days),
            )
        st.success(f"✅ 発行完了: 成功 {result['success']}件 / 失敗 {result['failure']}件")
        if result["failure"] > 0:
            with st.expander("❌ 失敗詳細"):
                for r in result["results"]:
                    if not r.get("ok"):
                        st.error(r.get("error"))
        st.rerun()
    except Exception as e:
        st.error("💥 発行処理中にエラーが発生しました。ネットワーク状況を確認して再度お試しください。")
        with st.expander("🔧 技術詳細（管理者向け）"):
            st.code(str(e), language=None)

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
    from utils.url_helper import get_base_host, contract_sign_url
    base_host = get_base_host()
    rows = []
    for c in contracts:
        token = c.get("signing_token") or ""
        url = contract_sign_url(token) if token else ""
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

    # --- コピー用URL（個別/一括） ---
    st.markdown("#### 📋 署名URLをコピー（LINE/メール貼付用）")
    pending_contracts = [c for c in contracts
                           if c["status"] in ("sent", "viewed") and c.get("signing_token")]
    if not pending_contracts:
        st.caption("未署名の契約はありません。")
    else:
        copy_mode2 = st.radio(
            "表示形式",
            ["個別（1名ずつ）", "一括（全員分まとめて）"],
            horizontal=True,
            key="contract_copy_mode",
        )
        if copy_mode2 == "個別（1名ずつ）":
            contract_choices = {
                f"{c['contract_no']} — {c.get('staff_name_jp')}（{c.get('staff_real_name') or '本名未登録'}）":
                contract_sign_url(c["signing_token"])
                for c in pending_contracts
            }
            picked2 = st.selectbox("契約選択", list(contract_choices.keys()),
                                    key="contract_pick")
            copyable_url(contract_choices[picked2], label="この契約の署名URL")
        else:
            bulk_text2 = "\n\n".join(
                f"{c.get('staff_real_name') or c.get('staff_name_jp')}さん\n"
                f"業務委託契約書の署名をお願いします。\n"
                + contract_sign_url(c["signing_token"])
                for c in pending_contracts
            )
            copyable_url(bulk_text2, label="全員分まとめて")

    # --- 📧 締結URLをメールで送信（2026-07-10 追加） ---
    st.markdown("#### 📧 締結URLをメールで送信")
    from utils import mailer as _mailer
    if not pending_contracts:
        st.caption("未締結の契約がないため、送信対象はありません。")
    elif not _mailer.mail_enabled():
        st.info(_mailer.mail_setup_hint())
    else:
        _ev = db.get_event_by_id(event_id) if event_id else {}
        _ev_name = (_ev or {}).get("name") or "P1大会"

        def _contract_mail_body(c, url):
            _name = c.get("staff_real_name") or c.get("staff_name_jp") or ""
            _exp = str(c.get("signing_token_expires_at") or "")[:10]
            _exp_line = f"※URLの有効期限: {_exp}\n" if _exp else ""
            return (
                f"{_name} 様\n\n"
                f"株式会社P1 Entertainmentです。\n"
                f"「{_ev_name}」の業務委託契約書をお送りします。\n\n"
                f"下記URLから内容をご確認のうえ、ページ下部の\n"
                f"「✅ 同意して契約を締結する」ボタンを押してください。\n"
                f"（署名の記入は不要です。ボタン押下で締結が完了します）\n\n"
                f"{url}\n\n"
                f"{_exp_line}"
                f"※本メールに心当たりがない場合は、破棄をお願いいたします。\n\n"
                f"株式会社P1 Entertainment\n"
            )

        _mailable = [c for c in pending_contracts if (c.get("staff_email") or "").strip()]
        _no_email = [c for c in pending_contracts if not (c.get("staff_email") or "").strip()]
        if _no_email:
            st.caption(
                f"⚠️ メールアドレス未登録のため送信できない契約が {len(_no_email)}件あります"
                "（👥 スタッフ管理で email を登録すると対象になります）。"
            )
        if _mailable:
            _mail_mode = st.radio(
                "送信方法", ["個別に送信", "未締結の全員に一括送信"],
                horizontal=True, key="contract_mail_mode",
            )
            _subject = f"【{_ev_name}】業務委託契約書のご確認・締結のお願い"
            if _mail_mode == "個別に送信":
                _opts = {
                    f"{c['contract_no']} — {c.get('staff_name_jp')}（{c.get('staff_email')}）": c
                    for c in _mailable
                }
                _picked = st.selectbox("送信先", list(_opts.keys()), key="contract_mail_pick")
                _c = _opts[_picked]
                _url = contract_sign_url(_c["signing_token"])
                with st.expander("📄 送信内容プレビュー"):
                    st.text(f"件名: {_subject}\n\n{_contract_mail_body(_c, _url)}")
                if st.button("📧 この1名に送信", type="primary", key="contract_mail_send_one"):
                    ok, err = _mailer.send_mail(
                        _c["staff_email"], _subject, _contract_mail_body(_c, _url))
                    if ok:
                        contract_db.mark_sent(_c["id"])
                        db.log_action("mail_contract_url", "contracts", _c["id"],
                                      detail=f"{_c['contract_no']} 締結URLをメール送信",
                                      event_id=event_id)
                        st.success(f"{_c.get('staff_name_jp')} さんに送信しました。")
                        st.rerun()
                    else:
                        st.error(f"送信失敗: {err}")
            else:
                st.caption(f"送信対象: {len(_mailable)}名（未締結・メール登録済み）")
                _confirm_bulk = st.checkbox(
                    f"{len(_mailable)}名への一括送信を確認しました",
                    key="contract_mail_bulk_confirm",
                )
                if st.button(f"📧 {len(_mailable)}名に一括送信", type="primary",
                              disabled=not _confirm_bulk, key="contract_mail_send_bulk"):
                    _ok_n, _fails = 0, []
                    _bar = st.progress(0.0)
                    for _i, _c in enumerate(_mailable, 1):
                        _url = contract_sign_url(_c["signing_token"])
                        ok, err = _mailer.send_mail(
                            _c["staff_email"], _subject, _contract_mail_body(_c, _url))
                        if ok:
                            _ok_n += 1
                            contract_db.mark_sent(_c["id"])
                        else:
                            _fails.append(f"{_c.get('staff_name_jp')}: {err}")
                        _bar.progress(_i / len(_mailable))
                    db.log_action("mail_contract_url_bulk", "contracts",
                                  detail=f"締結URL一括送信 成功{_ok_n}/失敗{len(_fails)}",
                                  event_id=event_id)
                    st.success(f"{_ok_n}名に送信しました。")
                    if _fails:
                        st.error("送信失敗:\n" + "\n".join(_fails[:10]))

    st.markdown("---")
    # CSV出力
    csv = df_contracts.to_csv(index=False).encode("utf-8-sig")
    st.warning(
        "⚠️ このCSVには氏名・署名URLが含まれます（T2個人情報）。送付前に受取人を確認してください。"
    )
    if st.checkbox("受取先を確認しました", key="dl_confirm_contracts"):
        st.download_button(
            "📥 署名URL一覧CSV",
            data=csv,
            file_name="contract_signing_urls.csv",
            mime="text/csv",
            key="dl_contracts_csv",
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

    # 無効化(revoke) UI
    with st.expander("🚫 契約を無効化する（誤発行の取り消し）"):
        st.caption("署名前の契約のみ無効化できます。無効化するとURLは失効します。")
        revokable = [c for c in contracts
                     if c["status"] in ("draft", "sent", "viewed")]
        if not revokable:
            st.caption("無効化可能な契約はありません。")
        else:
            rev_choices = {
                f"{c['contract_no']} — {c.get('staff_name_jp')} ({c['status']})": c["id"]
                for c in revokable
            }
            rev_pick = st.selectbox("無効化する契約", list(rev_choices.keys()),
                                      key="revoke_pick")
            rev_reason = st.text_input("無効化理由（任意・監査ログに記録されます）",
                                         key="revoke_reason")

            confirm_key = "__confirm_revoke"
            if st.session_state.get(confirm_key) != rev_choices[rev_pick]:
                if st.button("🚫 無効化する", key="start_revoke"):
                    st.session_state[confirm_key] = rev_choices[rev_pick]
                    st.rerun()
            else:
                st.warning(f"⚠️ 契約 `{rev_pick}` を無効化します。この操作は取り消せません。")
                col_r1, col_r2 = st.columns(2)
                if col_r1.button("✅ はい、無効化する", type="primary",
                                   key="do_revoke"):
                    try:
                        contract_db.revoke_contract(
                            rev_choices[rev_pick],
                            rev_reason or "理由記載なし",
                        )
                        st.success("✅ 無効化しました")
                        st.session_state[confirm_key] = None
                        st.rerun()
                    except Exception as e:
                        st.error("無効化に失敗しました。")
                        with st.expander("技術詳細"):
                            st.code(str(e))
                if col_r2.button("❌ キャンセル", key="cancel_revoke"):
                    st.session_state[confirm_key] = None
                    st.rerun()
