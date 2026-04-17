"""P1 Staff Manager — メインアプリ"""

import streamlit as st

st.set_page_config(
    page_title="P1 Staff Manager",
    page_icon="🃏",
    layout="wide",
    initial_sidebar_state="expanded",
)

from utils.ui_helpers import hide_staff_only_pages
hide_staff_only_pages()

st.title("🃏 P1 Staff Manager")
st.markdown("イベント経理管理システム")

st.divider()

# ============================================================
# 1行目: 基本機能
# ============================================================
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### 📋 スタッフ管理")
    st.markdown("スタッフの登録・検索・一覧表示")
    st.page_link("pages/1_スタッフ管理.py", label="スタッフ管理を開く", icon="📋")

with col2:
    st.markdown("### 📅 シフト取込")
    st.markdown("CSVからシフトを取り込み、自動で支払額を計算")
    st.page_link("pages/2_シフト取込.py", label="シフト取込を開く", icon="📅")

with col3:
    st.markdown("### 💰 支払い計算")
    st.markdown("時給×時間＋手当の自動計算")
    st.page_link("pages/3_支払い計算.py", label="支払い計算を開く", icon="💰")

# ============================================================
# 2行目: 現場オペレーション
# ============================================================
col4, col5, col6 = st.columns(3)

with col4:
    st.markdown("### ✉️ 封筒リスト")
    st.markdown("封筒ラベル＋紙幣内訳の出力")
    st.page_link("pages/4_封筒リスト.py", label="封筒リストを開く", icon="✉️")

with col5:
    st.markdown("### 🕐 出退勤")
    st.markdown("チェックイン/アウトの打刻・凍結退勤")
    st.page_link("pages/5_出退勤.py", label="出退勤を開く", icon="🕐")

with col6:
    st.markdown("### 📊 精算レポート")
    st.markdown("現金照合＋CSV出力")
    st.page_link("pages/6_精算レポート.py", label="精算レポートを開く", icon="📊")

# ============================================================
# 3行目: 集計系
# ============================================================
col7, col8, col9 = st.columns(3)

with col7:
    st.markdown("### 📆 年間累計")
    st.markdown("確定申告用・法定調書対象者一覧")
    st.page_link("pages/7_年間累計.py", label="年間累計を開く", icon="📆")

with col8:
    st.markdown("### 🚃 交通費")
    st.markdown("地域別上限・領収書入力・事前見積")
    st.page_link("pages/8_交通費.py", label="交通費を開く", icon="🚃")

with col9:
    st.markdown("### 📄 領収書発行")
    st.markdown("承認済み支払いを一括PDF化＋URL配布")
    st.page_link("pages/91_領収書発行.py", label="領収書発行を開く", icon="📄")

# ============================================================
# 4行目: 発行者・契約書系
# ============================================================
col10, col11, col12 = st.columns(3)

with col10:
    st.markdown("### 🏢 発行者設定")
    st.markdown("Pacific情報・インボイス番号（後日追加可）")
    st.page_link("pages/92_発行者設定.py", label="発行者設定を開く", icon="🏢")

with col11:
    st.markdown("### 📝 契約書テンプレ")
    st.markdown("業務委託契約・NDAテンプレートの編集")
    st.page_link("pages/93_契約書テンプレ.py", label="契約書テンプレを開く", icon="📝")

with col12:
    st.markdown("### ✍️ 契約書発行")
    st.markdown("スタッフへの一括発行＋署名状況確認")
    st.page_link("pages/94_契約書発行.py", label="契約書発行を開く", icon="✍️")

st.divider()

with st.expander("📘 スタッフ向けページ（管理者は通常使用しません）"):
    st.markdown("- `receipt download` — スタッフが領収書DL用URLからアクセス")
    st.markdown("- `contract sign` — スタッフが契約書署名用URLからアクセス")
    st.caption("トークン付きURL経由でのみ表示されるため、手動アクセス時は警告が出ます。")

st.caption("P1 Staff Manager v3.5 — 株式会社ヒダネ")
