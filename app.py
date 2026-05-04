"""P1 Staff Manager — メインアプリ（v3.7 新ホーム）

【ホームの3層構造】
  1. 状態ダッシュボード（今見るべき数字）
  2. 業務フローカード（①作る → ②入れる → ③計算 → ④渡す の順）
  3. 補助ツール（折りたたみ）
"""

import streamlit as st

st.set_page_config(
    page_title="P1 Staff Manager",
    page_icon="🃏",
    layout="wide",
    initial_sidebar_state="expanded",
)

import db  # noqa: E402
from utils.ui_helpers import hide_staff_only_pages  # noqa: E402
from utils.page_layout import (  # noqa: E402
    apply_global_style,
    page_header,
    flow_bar,
    kpi_card,
    action_card,
    section_header,
)


apply_global_style()
hide_staff_only_pages()


# ============================================================
# 1. ヘッダー
# ============================================================
page_header("🃏 P1 Staff Manager", "イベント経理管理システム")
flow_bar()


# ============================================================
# 2. 状態ダッシュボード
# ============================================================
def _build_status() -> dict:
    """ホーム表示用に最低限の集計を取得（失敗時は空で返す）"""
    out = {
        "active_event": None,
        "pending_count": 0,
        "pending_total": 0,
        "receipt_pending": 0,
        "approved_total": 0,
    }
    try:
        events = db.get_all_events() or []
        if events:
            # 一番直近のイベントを「進行中」として扱う
            out["active_event"] = events[0]
            payments = db.get_payments_for_event(events[0]["id"]) or []
            for p in payments:
                status = p.get("status", "pending")
                if status == "pending":
                    out["pending_count"] += 1
                    out["pending_total"] += int(p.get("total_amount") or 0)
                if status == "approved":
                    out["approved_total"] += int(p.get("total_amount") or 0)
                    if not p.get("receipt_received"):
                        out["receipt_pending"] += 1
    except Exception:
        # DB接続失敗等でも画面は壊さない
        pass
    return out


status = _build_status()
ev = status["active_event"]

st.markdown('<div class="p1-section"><h3>📊 今日のダッシュボード</h3></div>',
            unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1:
    if ev:
        kpi_card(
            "進行中のイベント",
            ev.get("name", "—"),
            f"{ev.get('start_date', '—')} 〜 {ev.get('end_date', '—')}　{ev.get('venue', '')}",
            accent=True,
        )
    else:
        kpi_card(
            "進行中のイベント",
            "未作成",
            "「📋 イベント設定」から最初の大会を作成してください",
        )
with col2:
    pending_total_str = f"¥{status['pending_total']:,}" if status["pending_total"] else "—"
    kpi_card(
        "未承認の支払い",
        f"{status['pending_count']}人",
        f"合計 {pending_total_str}　／ 承認済 ¥{status['approved_total']:,}",
        warning=(status["pending_count"] > 0),
    )
with col3:
    kpi_card(
        "領収書 配布待ち",
        f"{status['receipt_pending']}件",
        "支払済みのうち、領収書がまだ手元にあるもの",
        warning=(status["receipt_pending"] > 0),
    )


# ============================================================
# 3. 業務フローカード
# ============================================================
section_header("業務の流れ", "①作る → ②入れる → ③計算 → ④渡す の順で進めます")

# --- ① 作る ---
st.markdown('**STEP 1 — 作る**')
c1a, _, _ = st.columns(3)
with c1a:
    action_card(
        "STEP 1",
        "📋",
        "イベント設定",
        "新しい大会の『型』を1画面で組み立てる入口。JSONテンプレ／プリセット／手動編集に対応。",
        "pages/0_イベント設定.py",
    )

# --- ② 入れる ---
st.markdown('**STEP 2 — 入れる**')
c2a, c2b, _ = st.columns(3)
with c2a:
    action_card(
        "STEP 2",
        "👥",
        "スタッフ管理",
        "ディーラー・フロア・TD等のスタッフを登録。CSV/フォーム連携で一括取込も可能。",
        "pages/1_スタッフ管理.py",
    )
with c2b:
    action_card(
        "STEP 2",
        "📅",
        "シフト取込",
        "Googleスプレッドシートからシフト表を取り込み、自動で日別レートを補完。",
        "pages/2_シフト取込.py",
    )

# --- ③ 計算 ---
st.markdown('**STEP 3 — 計算**')
c3a, c3b, _ = st.columns(3)
with c3a:
    action_card(
        "STEP 3",
        "💰",
        "支払い計算",
        "時給×時間＋深夜＋手当＋精勤を自動計算。タイミー個別時給にも対応。",
        "pages/3_支払い計算.py",
    )
with c3b:
    action_card(
        "STEP 3",
        "✉️",
        "封筒リスト",
        "封筒ラベルと紙幣内訳（1万円札・5千円札・千円札）を一括出力。",
        "pages/4_封筒リスト.py",
    )

# --- ④ 渡す ---
st.markdown('**STEP 4 — 渡す**')
c4a, c4b, _ = st.columns(3)
with c4a:
    action_card(
        "STEP 4",
        "📄",
        "領収書発行",
        "承認済み支払いを一括PDF化＋スタッフ向けDL用URLを発行。",
        "pages/91_領収書発行.py",
    )
with c4b:
    action_card(
        "STEP 4",
        "✍️",
        "契約書発行",
        "業務委託契約・NDAをスタッフへ一括送付＋クラウド署名状況を追跡。",
        "pages/94_契約書発行.py",
    )


# ============================================================
# 4. 補助ツール（折りたたみ）
# ============================================================
section_header("補助ツール", "イベント中・締め後に使う機能")

with st.expander("🛠 開く", expanded=False):
    sup1, sup2, sup3 = st.columns(3)
    with sup1:
        action_card(
            "EVENT", "🕐",
            "出退勤",
            "チェックイン／アウトの打刻、凍結退勤、欠勤マーク。",
            "pages/5_出退勤.py",
        )
    with sup2:
        action_card(
            "REPORT", "📊",
            "精算レポート",
            "現金照合・小口現金・精算明細CSV出力。",
            "pages/6_精算レポート.py",
        )
    with sup3:
        action_card(
            "REPORT", "📆",
            "年間累計",
            "確定申告／法定調書対象者の年間累計。",
            "pages/7_年間累計.py",
        )

    sup4, sup5, sup6 = st.columns(3)
    with sup4:
        action_card(
            "SETUP", "🚃",
            "交通費",
            "地域別交通費ルール・領収書入力・事前見積り。",
            "pages/8_交通費.py",
        )
    with sup5:
        action_card(
            "SETUP", "🏢",
            "発行者設定",
            "Pacific 情報・インボイス番号・領収書用設定。",
            "pages/92_発行者設定.py",
        )
    with sup6:
        action_card(
            "SETUP", "📝",
            "契約書テンプレ",
            "業務委託契約・NDA テンプレートの編集。",
            "pages/93_契約書テンプレ.py",
        )


# ============================================================
# 5. スタッフ向けページの注意書き
# ============================================================
with st.expander("ℹ️ スタッフ向けページについて（管理者は通常使用しません）"):
    st.markdown(
        "- `receipt download` — スタッフが領収書DL用URLからアクセスする画面\n"
        "- `contract sign` — スタッフが契約書署名用URLからアクセスする画面\n"
        "\nどちらもトークン付きURL経由でのみ表示され、手動アクセス時は警告が出ます。"
    )


# ============================================================
# 6. フッター
# ============================================================
st.markdown(
    '<div style="margin-top: 48px; padding-top: 16px; '
    'border-top: 1px solid #E2E8F0; '
    'color: #94A3B8; font-size: 11.5px; text-align: center;">'
    'P1 Staff Manager v3.7 · 株式会社ヒダネ'
    '</div>',
    unsafe_allow_html=True,
)
