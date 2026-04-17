"""P1 Staff Manager — 封筒リスト＋紙幣内訳ページ"""

import streamlit as st
import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.denomination import (
    calculate_denomination, calculate_total_denomination,
    round_amount, format_denomination, DENOM_LABELS, DENOMINATIONS,
)
from utils.event_selector import select_event

st.set_page_config(page_title="封筒リスト", page_icon="✉️", layout="wide")
st.title("✉️ 封筒リスト")

# --- イベント選択（全ページ共通） ---
event_id = select_event(db.get_all_events(), "イベント選択")

# --- 設定 ---
st.subheader("設定")
col_s1, col_s2 = st.columns(2)
with col_s1:
    rounding = st.selectbox("端数処理", ["なし（そのまま）", "100円単位で切り上げ", "500円単位で切り上げ", "1000円単位で切り上げ"])
with col_s2:
    sort_by = st.selectbox("並び順", ["役職 → NO.", "名前順", "金額順（高い順）"])

rounding_unit = {"なし（そのまま）": 0, "100円単位で切り上げ": 100,
                 "500円単位で切り上げ": 500, "1000円単位で切り上げ": 1000}[rounding]

# --- データ取得 ---
payments = db.get_payments_for_event(event_id)
if not payments:
    st.warning("支払いデータがありません。先に「支払い計算」ページで計算を実行してください。")
    st.stop()

# 端数処理
envelope_data = []
for p in payments:
    amount = p["total_amount"]
    if rounding_unit > 0:
        amount = round_amount(amount, rounding_unit)
    breakdown = calculate_denomination(amount)
    envelope_data.append({
        **p,
        "adjusted_amount": amount,
        "denomination": breakdown,
    })

# 並び替え
if sort_by == "名前順":
    envelope_data.sort(key=lambda x: x["name_jp"])
elif sort_by == "金額順（高い順）":
    envelope_data.sort(key=lambda x: x["adjusted_amount"], reverse=True)

# --- サマリー ---
st.divider()
st.subheader("銀行で用意する現金")

total_amount = sum(e["adjusted_amount"] for e in envelope_data)
all_amounts = [e["adjusted_amount"] for e in envelope_data]
total_denoms = calculate_total_denomination(all_amounts)

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("総額", f"¥{total_amount:,}")
col_m2.metric("封筒数", f"{len(envelope_data)}枚")
if rounding_unit > 0:
    original_total = sum(p["total_amount"] for p in payments)
    col_m3.metric("端数切り上げ分", f"¥{total_amount - original_total:,}")

st.markdown("**紙幣・硬貨の必要数:**")
denom_cols = st.columns(len(total_denoms))
for i, (denom, count) in enumerate(sorted(total_denoms.items(), reverse=True)):
    with denom_cols[i] if i < len(denom_cols) else st.columns(1)[0]:
        st.metric(DENOM_LABELS.get(denom, f"¥{denom}"), f"{count}枚")

# --- 封筒リスト ---
st.divider()
st.subheader("封筒リスト")

display_data = []
for e in envelope_data:
    display_data.append({
        "NO.": e["no"],
        "名前": e["name_jp"],
        "役職": e["role"],
        "支払額": f"¥{e['adjusted_amount']:,}",
        "紙幣内訳": format_denomination(e["denomination"].bills),
        "支払状態": "✅" if e["status"] == "paid" else "⏳",
        "領収書": "✅" if e["receipt_received"] else "❌",
    })

df = pd.DataFrame(display_data)
st.dataframe(df, use_container_width=True, hide_index=True)

# --- 封筒ラベル印刷用 ---
st.divider()
st.subheader("封筒ラベル（印刷用）")

st.markdown("下記をコピーして封筒に貼る明細書として使用できます。")

for e in envelope_data:
    with st.expander(f"NO.{e['no']} {e['name_jp']}（{e['role']}）— ¥{e['adjusted_amount']:,}"):
        st.markdown(f"""
**━━━ P1 支払明細 ━━━**

| 項目 | 金額 |
|------|------|
| 基本給 | ¥{e['base_pay']:,} |
| 深夜手当 | ¥{e['night_pay']:,} |
| 交通費 | ¥{e['transport_total']:,} |
| フロア手当 | ¥{e['floor_bonus_total']:,} |
| MIX手当 | ¥{e['mix_bonus_total']:,} |
| 精勤手当 | ¥{e['attendance_bonus']:,} |
| **合計** | **¥{e['adjusted_amount']:,}** |

紙幣: {format_denomination(e['denomination'].bills)}
""")

# --- CSV出力 ---
st.divider()
st.subheader("CSV出力")

csv_data = []
for e in envelope_data:
    csv_data.append({
        "NO": e["no"],
        "名前_JP": e["name_jp"],
        "名前_EN": e.get("name_en", ""),
        "役職": e["role"],
        "基本給": e["base_pay"],
        "深夜手当": e["night_pay"],
        "交通費": e["transport_total"],
        "フロア手当": e["floor_bonus_total"],
        "MIX手当": e["mix_bonus_total"],
        "精勤手当": e["attendance_bonus"],
        "合計": e["adjusted_amount"],
        "支払状態": e["status"],
        "領収書": "受領済" if e["receipt_received"] else "未受領",
    })

csv_df = pd.DataFrame(csv_data)
csv_bytes = csv_df.to_csv(index=False).encode("utf-8-sig")
st.download_button("📥 CSVダウンロード", csv_bytes, "p1_envelope_list.csv", "text/csv")
