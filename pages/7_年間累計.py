"""P1 Staff Manager — 年間累計レポート（確定申告用）"""

import streamlit as st
import pandas as pd
from datetime import datetime
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db

st.set_page_config(page_title="年間累計", page_icon="📆", layout="wide")
st.title("📆 年間累計レポート（確定申告用）")
st.caption("1/1〜12/31の累計支払額。法定調書提出対象者（年¥50万超）を自動フラグ表示。")

EMPLOYMENT_LABELS = {
    "contractor": "業務委託",
    "timee": "タイミー",
    "fulltime": "正社員",
}

# --- 年選択 ---
current_year = datetime.now().year
year = st.selectbox("集計年", list(range(current_year + 1, current_year - 5, -1)), index=1)

# --- 雇用区分フィルタ ---
col_f1, col_f2 = st.columns(2)
with col_f1:
    emp_filter = st.selectbox(
        "雇用区分フィルタ",
        ["すべて"] + list(EMPLOYMENT_LABELS.values()),
    )
with col_f2:
    highlight_500k = st.checkbox("¥500,000超のみ表示（法定調書対象）", value=False)

# --- データ取得 ---
totals = db.get_yearly_totals(year)

if not totals:
    st.info(f"{year}年のデータはありません。")
    st.stop()

# フィルタ適用
if emp_filter != "すべて":
    emp_key = [k for k, v in EMPLOYMENT_LABELS.items() if v == emp_filter][0]
    totals = [t for t in totals if t["employment_type"] == emp_key]
if highlight_500k:
    totals = [t for t in totals if t["total_amount"] > 500000]

# --- サマリー ---
total_all = sum(t["total_amount"] for t in totals)
total_paid = sum(t["paid_amount"] for t in totals)
over_500k = sum(1 for t in totals if t["total_amount"] > 500000)

# 雇用区分別集計
by_emp = {}
for t in totals:
    emp = t["employment_type"] or "contractor"
    if emp not in by_emp:
        by_emp[emp] = {"count": 0, "total": 0}
    by_emp[emp]["count"] += 1
    by_emp[emp]["total"] += t["total_amount"]

col1, col2, col3, col4 = st.columns(4)
col1.metric(f"{year}年総支払額", f"¥{total_all:,}")
col2.metric("支払済み合計", f"¥{total_paid:,}")
col3.metric("対象人数", f"{len(totals)}名")
col4.metric("¥500,000超", f"{over_500k}名",
            delta="法定調書対象" if over_500k > 0 else None,
            delta_color="off")

# --- 雇用区分別 ---
st.divider()
st.subheader("雇用区分別集計")
emp_rows = []
for emp_key, data in sorted(by_emp.items()):
    emp_rows.append({
        "区分": EMPLOYMENT_LABELS.get(emp_key, emp_key),
        "人数": f"{data['count']}名",
        "合計": f"¥{data['total']:,}",
        "平均": f"¥{data['total'] // data['count']:,}" if data["count"] else "—",
    })
st.dataframe(pd.DataFrame(emp_rows), use_container_width=True, hide_index=True)

# --- スタッフ別年間累計 ---
st.divider()
st.subheader("スタッフ別年間累計（金額降順）")

display = []
for t in totals:
    over_flag = "🔴 対象" if t["total_amount"] > 500000 else ""
    display.append({
        "NO.": t["no"],
        "ディーラーネーム": t["name_jp"],
        "本名": t.get("real_name") or "—",
        "区分": EMPLOYMENT_LABELS.get(t["employment_type"] or "contractor", "—"),
        "役職": t["role"],
        "参加大会数": t["event_count"],
        "参加大会": ", ".join(t["event_names"][:3]) + ("..." if len(t["event_names"]) > 3 else ""),
        "年間総額": f"¥{t['total_amount']:,}",
        "うち支払済": f"¥{t['paid_amount']:,}",
        "法定調書": over_flag,
    })

df = pd.DataFrame(display)
st.dataframe(df, use_container_width=True, hide_index=True, height=600)

# --- 法定調書対象者リスト ---
st.divider()
st.subheader("⚠️ 法定調書提出対象者（年間¥500,000超）")
target_staff = [t for t in totals if t["total_amount"] > 500000]
if target_staff:
    st.warning(f"{len(target_staff)}名が¥500,000を超えています。下記情報で法定調書を準備してください。")
    for t in target_staff:
        with st.expander(f"🔴 {t['name_jp']}（本名: {t.get('real_name') or '未登録'}）— ¥{t['total_amount']:,}"):
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"""
- **NO.**: {t['no']}
- **ディーラーネーム**: {t['name_jp']}
- **本名**: {t.get('real_name') or '⚠️ 未登録'}
- **雇用区分**: {EMPLOYMENT_LABELS.get(t['employment_type'] or 'contractor')}
- **役職**: {t['role']}
""")
            with col_b:
                st.markdown(f"""
- **住所**: {t.get('address') or '⚠️ 未登録'}
- **メール**: {t.get('email') or '⚠️ 未登録'}
- **年間総額**: ¥{t['total_amount']:,}
- **参加大会**: {t['event_count']}回
""")
            if not t.get("real_name") or not t.get("address"):
                col_err, col_link = st.columns([3, 1])
                col_err.error("❌ 本名または住所が未登録です（法定調書作成に必要）")
                col_link.page_link("pages/1_staff.py", label="▶ スタッフ管理へ", icon="📋")
else:
    st.success("¥500,000超のスタッフはいません。")

# --- CSV出力 ---
st.divider()
csv_data = []
for t in totals:
    csv_data.append({
        "NO": t["no"],
        "ディーラーネーム": t["name_jp"],
        "本名": t.get("real_name") or "",
        "住所": t.get("address") or "",
        "メール": t.get("email") or "",
        "雇用区分": EMPLOYMENT_LABELS.get(t["employment_type"] or "contractor"),
        "役職": t["role"],
        "参加大会数": t["event_count"],
        "参加大会一覧": " / ".join(t["event_names"]),
        "年間総額": t["total_amount"],
        "うち支払済": t["paid_amount"],
        "法定調書対象": "対象" if t["total_amount"] > 500000 else "",
    })
csv_bytes = pd.DataFrame(csv_data).to_csv(index=False).encode("utf-8-sig")
st.download_button(
    f"📥 {year}年 年間累計CSVダウンロード",
    csv_bytes,
    f"p1_yearly_{year}.csv",
    "text/csv",
)
