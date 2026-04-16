"""P1 Staff Manager — メインアプリ"""

import streamlit as st

st.set_page_config(
    page_title="P1 Staff Manager",
    page_icon="🃏",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🃏 P1 Staff Manager")
st.markdown("イベント経理管理システム")

st.divider()

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### 📋 スタッフ管理")
    st.markdown("スタッフの登録・検索・一覧表示")
    st.page_link("pages/1_staff.py", label="スタッフ管理を開く", icon="📋")

with col2:
    st.markdown("### 📅 シフト取込")
    st.markdown("CSVからシフトを取り込み、自動で支払額を計算")
    st.page_link("pages/2_shift.py", label="シフト取込を開く", icon="📅")

with col3:
    st.markdown("### 💰 支払い計算")
    st.markdown("時給×時間＋手当の自動計算")
    st.page_link("pages/3_payment.py", label="支払い計算を開く", icon="💰")

col4, col5, col6 = st.columns(3)

with col4:
    st.markdown("### ✉️ 封筒リスト")
    st.markdown("封筒ラベル＋紙幣内訳の出力")
    st.page_link("pages/4_envelope.py", label="封筒リストを開く", icon="✉️")

with col5:
    st.markdown("### 🕐 出退勤")
    st.markdown("チェックイン/アウトの打刻")
    st.page_link("pages/5_attendance.py", label="出退勤を開く", icon="🕐")

with col6:
    st.markdown("### 📊 精算レポート")
    st.markdown("現金照合＋CSV出力")
    st.page_link("pages/6_report.py", label="精算レポートを開く", icon="📊")

col7, col8, _ = st.columns(3)

with col7:
    st.markdown("### 📆 年間累計")
    st.markdown("確定申告用・法定調書対象者一覧")
    st.page_link("pages/7_yearly.py", label="年間累計を開く", icon="📆")

with col8:
    st.markdown("### 🚃 交通費")
    st.markdown("地域別上限・領収書入力・事前見積")
    st.page_link("pages/8_transport.py", label="交通費を開く", icon="🚃")

st.divider()
st.caption("P1 Staff Manager v3.2 — 株式会社ヒダネ")
