"""P1 Staff Manager — 精算レポートページ"""

import streamlit as st
import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.event_selector import select_event

st.set_page_config(page_title="精算レポート", page_icon="📊", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
hide_staff_only_pages()
st.title("📊 精算レポート")

# --- イベント選択（全ページ共通） ---
event_id = select_event(db.get_all_events(), "イベント選択")

# --- 支払い状況 ---
payments = db.get_payments_for_event(event_id)

if not payments:
    st.info("支払いデータがありません。")
    st.stop()

st.subheader("支払い状況サマリー")

total_amount = sum(p["total_amount"] for p in payments)
paid_count = sum(1 for p in payments if p["status"] == "paid")
unpaid_count = sum(1 for p in payments if p["status"] != "paid")
receipt_count = sum(1 for p in payments if p["receipt_received"])
no_receipt_count = sum(1 for p in payments if not p["receipt_received"])
paid_amount = sum(p["total_amount"] for p in payments if p["status"] == "paid")
unpaid_amount = sum(p["total_amount"] for p in payments if p["status"] != "paid")

col1, col2, col3 = st.columns(3)
col1.metric("総支払額", f"¥{total_amount:,}")
col2.metric("支払済み", f"¥{paid_amount:,}", delta=f"{paid_count}名")
col3.metric("未払い", f"¥{unpaid_amount:,}", delta=f"{unpaid_count}名", delta_color="inverse")

col4, col5, col6 = st.columns(3)
col4.metric("対象人数", f"{len(payments)}名")
col5.metric("領収書受領済み", f"{receipt_count}名")
col6.metric("領収書未受領", f"{no_receipt_count}名", delta_color="inverse")

# --- 内訳 ---
st.divider()
st.subheader("支払い内訳")

breakdown = {
    "基本給": sum(p["base_pay"] for p in payments),
    "深夜手当": sum(p["night_pay"] for p in payments),
    "交通費": sum(p["transport_total"] for p in payments),
    "フロア手当": sum(p["floor_bonus_total"] for p in payments),
    "MIX手当": sum(p["mix_bonus_total"] for p in payments),
    "精勤手当": sum(p["attendance_bonus"] for p in payments),
}

breakdown_df = pd.DataFrame([
    {"項目": k, "金額": v, "構成比": f"{v / total_amount * 100:.1f}%"}
    for k, v in breakdown.items()
])
breakdown_df["金額表示"] = breakdown_df["金額"].apply(lambda x: f"¥{x:,}")

col_chart, col_table = st.columns([1, 1])
with col_chart:
    st.bar_chart(breakdown_df.set_index("項目")["金額"])
with col_table:
    st.dataframe(
        breakdown_df[["項目", "金額表示", "構成比"]],
        use_container_width=True,
        hide_index=True,
    )

# --- 役職別集計 ---
st.divider()
st.subheader("役職別集計")

role_summary = {}
for p in payments:
    role = p["role"]
    if role not in role_summary:
        role_summary[role] = {"人数": 0, "合計": 0, "平均": 0}
    role_summary[role]["人数"] += 1
    role_summary[role]["合計"] += p["total_amount"]

for role in role_summary:
    role_summary[role]["平均"] = role_summary[role]["合計"] // role_summary[role]["人数"]

role_df = pd.DataFrame([
    {
        "役職": role,
        "人数": f"{data['人数']}名",
        "合計": f"¥{data['合計']:,}",
        "平均": f"¥{data['平均']:,}",
    }
    for role, data in sorted(role_summary.items())
])
st.dataframe(role_df, use_container_width=True, hide_index=True)

# --- 雇用区分別集計 ---
st.divider()
st.subheader("雇用区分別集計（業務委託 / タイミー / 正社員）")

EMPLOYMENT_LABELS = {
    "contractor": "業務委託",
    "timee": "タイミー",
    "fulltime": "正社員",
}

# 全スタッフの雇用区分を取得
all_staff_map = {s["id"]: s for s in db.get_all_staff()}
emp_summary = {}
for p in payments:
    staff = all_staff_map.get(p["staff_id"])
    emp_type = (staff.get("employment_type") if staff else None) or "contractor"
    label = EMPLOYMENT_LABELS.get(emp_type, emp_type)
    if label not in emp_summary:
        emp_summary[label] = {"人数": 0, "合計": 0}
    emp_summary[label]["人数"] += 1
    emp_summary[label]["合計"] += p["total_amount"]

emp_df = pd.DataFrame([
    {
        "区分": label,
        "人数": f"{data['人数']}名",
        "合計": f"¥{data['合計']:,}",
        "平均": f"¥{data['合計'] // data['人数']:,}" if data["人数"] else "—",
    }
    for label, data in emp_summary.items()
])
st.dataframe(emp_df, use_container_width=True, hide_index=True)

# 人件費トータル（業務委託+タイミー+正社員）の表示
total_labor = sum(d["合計"] for d in emp_summary.values())
st.metric("人件費トータル（全区分合計）", f"¥{total_labor:,}")

# --- 小口経費 ---
st.divider()
st.subheader("小口経費")

petty = db.get_petty_cash_for_event(event_id)
if petty:
    petty_total = sum(p["amount"] for p in petty)
    st.metric("小口経費合計", f"¥{petty_total:,}")

    petty_df = pd.DataFrame(petty)
    display_cols = ["date", "description", "amount", "requester", "approver", "status"]
    available = [c for c in display_cols if c in petty_df.columns]
    st.dataframe(petty_df[available], use_container_width=True, hide_index=True)
else:
    st.info("小口経費の記録はありません。")

# 小口経費追加
with st.expander("➕ 小口経費を追加"):
    with st.form("add_petty"):
        pc_date = st.date_input("日付")
        pc_desc = st.text_input("内容", placeholder="例: タクシー代（会場→ホテル）")
        pc_amount = st.number_input("金額 (円)", min_value=0, step=100)
        pc_requester = st.text_input("申請者")
        pc_approver = st.text_input("承認者")
        if st.form_submit_button("追加"):
            if pc_desc and pc_amount > 0:
                db.add_petty_cash(event_id, str(pc_date), pc_desc, pc_amount, pc_requester, pc_approver)
                st.success("小口経費を追加しました")
                st.rerun()

# --- 未払い・未受領リスト ---
st.divider()
st.subheader("⚠️ 未処理リスト")

unpaid = [p for p in payments if p["status"] != "paid"]
no_receipt = [p for p in payments if not p["receipt_received"]]

col_u1, col_u2 = st.columns(2)

with col_u1:
    st.markdown(f"**未払い（{len(unpaid)}名）**")
    if unpaid:
        for p in unpaid:
            st.warning(f"NO.{p['no']} {p['name_jp']} — ¥{p['total_amount']:,}")
    else:
        st.success("全員支払い済み")

with col_u2:
    st.markdown(f"**領収書未受領（{len(no_receipt)}名）**")
    if no_receipt:
        for p in no_receipt:
            st.warning(f"NO.{p['no']} {p['name_jp']} — ¥{p['total_amount']:,}")
    else:
        st.success("全員領収書受領済み")

# --- CSV一括出力 ---
st.divider()
st.subheader("📥 データ出力")

col_dl1, col_dl2 = st.columns(2)

with col_dl1:
    # 支払い一覧CSV
    csv_payment = []
    for p in payments:
        csv_payment.append({
            "NO": p["no"],
            "名前_JP": p["name_jp"],
            "名前_EN": p.get("name_en", ""),
            "役職": p["role"],
            "基本給": p["base_pay"],
            "深夜手当": p["night_pay"],
            "交通費": p["transport_total"],
            "フロア手当": p["floor_bonus_total"],
            "MIX手当": p["mix_bonus_total"],
            "精勤手当": p["attendance_bonus"],
            "合計": p["total_amount"],
            "支払状態": "支払済" if p["status"] == "paid" else "未払",
            "領収書": "受領済" if p["receipt_received"] else "未受領",
            "支払日": p.get("paid_at", ""),
        })
    payment_csv = pd.DataFrame(csv_payment).to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 支払い一覧CSV", payment_csv, "p1_payments.csv", "text/csv")

with col_dl2:
    # 小口経費CSV
    if petty:
        petty_csv = pd.DataFrame(petty).to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 小口経費CSV", petty_csv, "p1_petty_cash.csv", "text/csv")
