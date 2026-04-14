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
    st.page_link("pages/1_📋_スタッフ管理.py", label="スタッフ管理を開く", icon="📋")

with col2:
    st.markdown("### 📅 シフト取込")
    st.markdown("CSVからシフトを取り込み、自動で支払額を計算")
    st.page_link("pages/2_📅_シフト取込.py", label="シフト取込を開く", icon="📅")

with col3:
    st.markdown("### 💰 支払い計算")
    st.markdown("時給×時間＋手当の自動計算")
    st.page_link("pages/3_💰_支払い計算.py", label="支払い計算を開く", icon="💰")

col4, col5, col6 = st.columns(3)

with col4:
    st.markdown("### ✉️ 封筒リスト")
    st.markdown("封筒ラベル＋紙幣内訳の出力")
    st.page_link("pages/4_✉️_封筒リスト.py", label="封筒リストを開く", icon="✉️")

with col5:
    st.markdown("### 🕐 出退勤")
    st.markdown("チェックイン/アウトの打刻")
    st.page_link("pages/5_🕐_出退勤.py", label="出退勤を開く", icon="🕐")

with col6:
    st.markdown("### 📊 精算レポート")
    st.markdown("現金照合＋CSV出力")
    st.page_link("pages/6_📊_精算レポート.py", label="精算レポートを開く", icon="📊")

st.divider()
st.caption("P1 Staff Manager v0.1 — 株式会社ヒダネ")
