"""P1 Staff Manager — 支払い管理（経理）

2026-08-14 中野さん指示で「封筒リスト」を全面刷新:
    早入り・残業で金額が予定と違うため封筒の事前準備は成立しない（廃止）。
    代わりに「誰にいくら・現金か後日振込か・支払い済みか」を経理が管理する。

支払い方法は utils/payment_method（p1_payments.notes の先頭マーカー方式）。
状態遷移は従来のまま: pending（打刻で変動）→ approved（金額確定）→ paid。
paid を「現金支払い済み」と「振込済み」に分けるのは方法マーカーで行う。
"""

import io

import streamlit as st
import pandas as pd
import sys
import os
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.event_selector import select_event

st.set_page_config(page_title="支払い管理", page_icon="💴", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import (
    apply_global_style, page_header, flow_bar, section_header, kpi_row,
)
from utils.roles import DEPT_CHOICES, role_dept
from utils import payment_method as pm
from utils.admin_guard import require_admin, admin_logout_button, operator_name
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="支払い管理")
admin_logout_button()

_JST = timezone(timedelta(hours=9))

page_header("💴 支払い管理（経理）",
            "誰にいくら・現金か後日振込か・支払い済みかを一元管理します。"
            "封筒の事前準備は廃止（早入り・残業で金額が動くため、清算はピット画面の確定額で行います）。")
flow_bar(active="calc", done=["setup", "input"])

db.log_action("view_payment_admin", "payments", detail="page=支払い管理",
              performed_by=operator_name())

event_id = select_event(db.get_all_events(), "イベント")

# フラッシュ（st.success+rerunで消えるのを防ぐ）
if st.session_state.get("_pay_admin_flash"):
    st.success(st.session_state.pop("_pay_admin_flash"))

# --- データ取得 ---
payments = db.get_payments_for_event(event_id)
if not payments:
    st.info("支払いデータがありません。先に「💰 支払い計算」を実行してください。")
    st.stop()
smap = {s["id"]: s for s in db.get_all_staff()}

_dept = st.radio("部門", list(DEPT_CHOICES), horizontal=True, key="pay_admin_dept")
_method_f = st.radio("支払い方法で絞る", ["すべて", "現金", "後日振込"],
                     horizontal=True, key="pay_admin_method")

rows = []
for p in payments:
    stf = smap.get(p["staff_id"], {})
    if _dept != "全員" and role_dept(stf.get("role")) != _dept:
        continue
    m = pm.method_of(p)
    if _method_f == "現金" and m != "cash":
        continue
    if _method_f == "後日振込" and m != "transfer":
        continue
    rows.append({
        "NO.": stf.get("no"),
        "名前": stf.get("name_jp", "?"),
        "役職": stf.get("role") or "—",
        "確定額": db.get_payable(p),
        "後日振込": m == "transfer",
        "状態": pm.state_label(p),
        "支払日時": (p.get("paid_at") or "")[:16].replace("T", " "),
        "メモ": pm.free_note(p),
        "_pid": p["id"],
        "_status": p["status"],
        "_staff_id": p["staff_id"],
    })
rows.sort(key=lambda r: (r["NO."] or 9999))

# --- サマリー ---
def _sum(cond):
    return sum(r["確定額"] for r in rows if cond(r))

kpi_row([
    ("✅ 現金支払い済み", f"¥{_sum(lambda r: r['_status'] == 'paid' and not r['後日振込']):,}",
     f"{sum(1 for r in rows if r['_status'] == 'paid' and not r['後日振込'])}名"),
    ("✅ 振込済み", f"¥{_sum(lambda r: r['_status'] == 'paid' and r['後日振込']):,}",
     f"{sum(1 for r in rows if r['_status'] == 'paid' and r['後日振込'])}名"),
    ("🏦 振込待ち（確定）", f"¥{_sum(lambda r: r['_status'] == 'approved' and r['後日振込']):,}",
     f"{sum(1 for r in rows if r['_status'] == 'approved' and r['後日振込'])}名"),
    ("⏳ 金額変動中", f"¥{_sum(lambda r: r['_status'] == 'pending'):,}",
     f"{sum(1 for r in rows if r['_status'] == 'pending')}名"),
])

# ============================================================
# ① 一覧＋方法の切り替え（「後日振込」チェックを直接編集）
# ============================================================
section_header("① 支払い一覧",
               "「後日振込」列のチェックで方法を切り替えます（支払い済みの人は変更不可）。"
               "金額は打刻・再計算に自動追随し、確定するとピット清算／この画面の記録対象になります。")

df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")}
                   | {"_pid": r["_pid"], "_status": r["_status"]} for r in rows])
edited = st.data_editor(
    df,
    use_container_width=True, hide_index=True, height=560,
    disabled=["NO.", "名前", "役職", "確定額", "状態", "支払日時", "メモ",
              "_pid", "_status"],
    column_config={
        "確定額": st.column_config.NumberColumn("確定額", format="¥%d"),
        "後日振込": st.column_config.CheckboxColumn(
            "後日振込", help="チェック＝後日振込／外す＝現金（会場渡し）"),
        "_pid": None, "_status": None,
    },
    key="pay_admin_table",
)
if not df.empty:
    for i in range(len(df)):
        if bool(df.iloc[i]["後日振込"]) != bool(edited.iloc[i]["後日振込"]):
            if df.iloc[i]["_status"] == "paid":
                st.session_state["_pay_admin_flash"] = (
                    f"⚠️ {df.iloc[i]['名前']} は支払い済みのため方法を変更できません。")
                st.rerun()
            pm.set_method(int(df.iloc[i]["_pid"]),
                          "transfer" if edited.iloc[i]["後日振込"] else "cash",
                          performed_by=operator_name())
            st.session_state["_pay_admin_flash"] = (
                f"💾 {df.iloc[i]['名前']} を"
                f"{'後日振込' if edited.iloc[i]['後日振込'] else '現金'}にしました。")
            st.rerun()

# ============================================================
# ② 振込の実行記録（経理）
# ============================================================
section_header("② 振込済みにする",
               "銀行で振込を実行したら、ここで記録します（対象＝金額確定済みの振込待ち）。")
_wait = [r for r in rows if r["_status"] == "approved" and r["後日振込"]]
if not _wait:
    st.info("振込待ち（金額確定済み）の人はいません。"
            "金額が変動中の人は、ピットでの実績確定または「💰 支払い計算」の承認後にここへ出ます。")
else:
    _opts = {f"NO.{r['NO.']} {r['名前']} — ¥{r['確定額']:,}": r for r in _wait}
    _sel = st.multiselect("振込を実行した人", list(_opts.keys()), key="transfer_done_sel")
    if st.button(f"🏦 選択した {len(_sel)}名 を振込済みにする", type="primary",
                 disabled=not _sel, key="transfer_done_btn"):
        ok_n = 0
        for k in _sel:
            r = _opts[k]
            if db.mark_paid(r["_pid"], event_id=event_id,
                            performed_by=f"振込:{operator_name()}"):
                ok_n += 1
        st.session_state["_pay_admin_flash"] = (
            f"✅ {ok_n}名を振込済みにしました。領収書が必要な場合は"
            "「📄 領収書発行」ページからメール送付できます。")
        st.rerun()

# ============================================================
# ③ 振込リストのダウンロード（銀行手続き用）
# ============================================================
section_header("③ 振込リスト", "振込待ちの人をCSVで出せます（本名・金額入り。取扱注意）。")
if _wait:
    _csv_rows = []
    for r in _wait:
        stf = smap.get(r["_staff_id"], {})
        _csv_rows.append({
            "NO": r["NO."], "活動名義": r["名前"],
            "本名": stf.get("real_name") or "",
            "金額": r["確定額"], "メモ": r["メモ"],
        })
    _buf = io.StringIO()
    pd.DataFrame(_csv_rows).to_csv(_buf, index=False)
    st.download_button(
        f"⬇️ 振込リストCSV（{len(_csv_rows)}名・¥{sum(x['金額'] for x in _csv_rows):,}）",
        _buf.getvalue().encode("utf-8-sig"),
        file_name=f"transfer_list_{datetime.now(_JST).strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv", key="transfer_csv_dl")
else:
    st.caption("振込待ちの人が出るとここからCSVを出せます。")

st.divider()
st.caption(
    "💡 運用メモ: 現金の人はピット画面で「支払い確定」→ その場で現金と領収書。"
    "後日振込の人はピットで実績確定だけ行い（現金は渡さない）、"
    "経理がこの画面で振込済みを記録します。旧・封筒リスト（紙幣内訳の事前準備）は"
    "早入り・残業で金額が動くため廃止しました。"
)
