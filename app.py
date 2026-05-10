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
    progress_checklist,
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
    """ホーム表示用に最低限の集計を取得（失敗時は空で返す）

    UX A (2026-05-09): 「今日のTo-Do」用の進捗情報を追加で集計
    """
    out = {
        "active_event": None,
        "pending_count": 0,
        "pending_total": 0,
        "approved_count": 0,
        "approved_total": 0,
        "paid_count": 0,
        "receipt_pending": 0,
        # UX A: To-Do 判定用
        "staff_count": 0,
        "shift_count": 0,
        "rates_count": 0,
        "exception_count": 0,
        "exception_unconfirmed": 0,
        "payment_count": 0,
        # Codex P2 #14 fix: 期待される支払いスタッフ数（出勤シフトのある人数）
        "expected_paid_staff": 0,
    }
    try:
        events = db.get_all_events() or []
        if events:
            # 一番直近のイベントを「進行中」として扱う
            ev = events[0]
            out["active_event"] = ev
            event_id = ev["id"]

            # スタッフ数（全イベント横断的）
            try:
                out["staff_count"] = len(db.get_all_staff() or [])
            except Exception:
                pass
            # シフト数（このイベント）
            try:
                shifts = db.get_shifts_for_event(event_id) or []
                out["shift_count"] = len(shifts)
                # Codex P3 #16 fix (2026-05-09): 例外判定を厳密化
                # 「実績が予定とズレている」or「欠勤」のみ例外としてカウント
                # （普通に出退勤しただけのシフトは正常扱い）
                _exception_count = 0
                for s in shifts:
                    if s.get("status") == "absent":
                        _exception_count += 1
                        continue
                    actual_start = s.get("actual_start")
                    actual_end = s.get("actual_end")
                    planned_start = s.get("planned_start")
                    planned_end = s.get("planned_end")
                    # 実績が記録されていて、かつ予定と異なる場合のみ例外
                    if actual_start and planned_start and actual_start != planned_start:
                        _exception_count += 1
                    elif actual_end and planned_end and actual_end != planned_end:
                        _exception_count += 1
                out["exception_count"] = _exception_count
                # 未確定（scheduled）
                out["exception_unconfirmed"] = sum(
                    1 for s in shifts if s.get("status") == "scheduled"
                )
                # Codex P2 #14 fix: 出勤シフトを持つスタッフ数（欠勤除く）
                # 支払い計算が必要なスタッフ数を期待値として保持
                _expected_staff_ids = {
                    s.get("staff_id") for s in shifts
                    if s.get("status") != "absent" and s.get("staff_id")
                }
                out["expected_paid_staff"] = len(_expected_staff_ids)
            except Exception:
                pass
            # レート数
            try:
                out["rates_count"] = len(db.get_event_rates(event_id) or [])
            except Exception:
                pass

            payments = db.get_payments_for_event(event_id) or []
            out["payment_count"] = len(payments)
            for p in payments:
                status = p.get("status", "pending")
                if status == "pending":
                    out["pending_count"] += 1
                    out["pending_total"] += int(p.get("total_amount") or 0)
                elif status == "approved":
                    out["approved_count"] += 1
                    out["approved_total"] += int(p.get("total_amount") or 0)
                    if not p.get("receipt_received"):
                        out["receipt_pending"] += 1
                elif status == "paid":
                    out["paid_count"] += 1
    except Exception:
        # DB接続失敗等でも画面は壊さない
        pass
    return out


status = _build_status()
ev = status["active_event"]

# ============================================================
# UX A: 今日のTo-Doリスト（最上部・一番大きい）
# ============================================================
st.markdown('<div class="p1-section"><h3>✅ 今日のTo-Do</h3>'
            '<p class="p1-section-help">大会のセットアップから締めまでの進捗。'
            'リストの上から順に進めれば締めまで届きます。</p></div>',
            unsafe_allow_html=True)


def _todo_status(condition_done: bool, condition_warn: bool = False,
                 has_started: bool = True) -> str:
    if condition_done:
        return "done"
    if condition_warn:
        return "warn"
    if has_started:
        return "pending"
    return "todo"


if ev:
    # 各タスクの状態判定
    todo_items = [
        {
            "label": f"イベント作成: {ev.get('name', '—')}",
            "detail": f"{ev.get('start_date', '—')} 〜 {ev.get('end_date', '—')}  ／ 会場: {ev.get('venue', '')}",
            "status": "done",
        },
        {
            "label": "レート設定（日別単価）",
            "detail": f"{status['rates_count']}日分 設定済み"
                      if status['rates_count'] else "未設定 — シフト取込で自動補完されます",
            "status": _todo_status(
                status['rates_count'] > 0,
                False,
            ),
            "page": "pages/0_イベント設定.py",
            "page_label": "📋 イベント設定を開く",
        },
        {
            "label": "スタッフ登録",
            "detail": f"{status['staff_count']}名 登録済み"
                      if status['staff_count'] else "未登録",
            "status": _todo_status(
                status['staff_count'] >= 5,
                0 < status['staff_count'] < 5,
            ),
            "page": "pages/1_スタッフ管理.py",
            "page_label": "👥 スタッフ管理を開く",
        },
        {
            "label": "シフト取込",
            "detail": f"{status['shift_count']}件 取込済み"
                      if status['shift_count'] else "未取込",
            "status": _todo_status(
                status['shift_count'] >= 10,
                0 < status['shift_count'] < 10,
            ),
            "page": "pages/2_シフト取込.py",
            "page_label": "📅 シフト取込を開く",
        },
        {
            "label": "出退勤の例外記録",
            "detail": (
                f"未確定 {status['exception_unconfirmed']}人 ／ 例外記録 {status['exception_count']}件"
                if status['shift_count'] else "シフト取込後に確認できます"
            ),
            "status": _todo_status(
                status['shift_count'] > 0 and status['exception_unconfirmed'] == 0,
                status['exception_unconfirmed'] > 0,
            ),
            "page": "pages/5_出退勤.py",
            "page_label": "🕐 出退勤を開く",
        },
        {
            "label": "支払い計算",
            "detail": (
                # Codex P2 #14 fix: 期待スタッフ数と比較
                f"計算済み {status['payment_count']}/{status['expected_paid_staff']}人 ／ "
                f"未承認 {status['pending_count']}人"
                if status['payment_count'] else (
                    f"未実行（対象 {status['expected_paid_staff']}人）"
                    if status['expected_paid_staff']
                    else "未実行"
                )
            ),
            "status": _todo_status(
                # 完了条件: 期待スタッフ全員分の計算 + 未承認ゼロ
                (status['expected_paid_staff'] > 0
                 and status['payment_count'] >= status['expected_paid_staff']
                 and status['pending_count'] == 0),
                status['pending_count'] > 0
                or (status['expected_paid_staff'] > 0
                    and status['payment_count'] < status['expected_paid_staff']),
            ),
            "page": "pages/3_支払い計算.py",
            "page_label": "💰 支払い計算を開く",
        },
        {
            "label": "領収書受領",
            "detail": (
                f"配布待ち {status['receipt_pending']}件" if status['receipt_pending']
                else (f"全員受領済み（{status['approved_count']}人）"
                      if status['approved_count'] else "承認後に表示されます")
            ),
            "status": _todo_status(
                status['approved_count'] > 0 and status['receipt_pending'] == 0,
                status['receipt_pending'] > 0,
            ),
            "page": "pages/91_領収書発行.py",
            "page_label": "📄 領収書発行を開く",
        },
        {
            "label": "支払い完了",
            "detail": (
                # Codex P2 #14 fix: 期待数と比較
                f"{status['paid_count']}/{status['expected_paid_staff']}人 支払済み"
                if status['expected_paid_staff'] else (
                    f"{status['paid_count']}人 支払済み"
                    if status['payment_count'] else "計算後に表示されます"
                )
            ),
            "status": _todo_status(
                # 完了条件: 期待スタッフ全員分が paid 状態
                (status['expected_paid_staff'] > 0
                 and status['paid_count'] >= status['expected_paid_staff']),
                0 < status['paid_count'] < (status['expected_paid_staff']
                                            or status['payment_count']),
            ),
            "page": "pages/6_精算レポート.py",
            "page_label": "📊 精算レポートを開く",
        },
    ]
    progress_checklist(todo_items)
else:
    st.warning(
        "⚠️ まだイベントが作成されていません。"
        "下のカード「📋 イベント設定」から最初の大会を作成してください。"
    )

st.markdown('<div class="p1-section"><h3>📊 数字でみる現状</h3></div>',
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
c3a, c3b, c3c = st.columns(3)
with c3a:
    action_card(
        "STEP 3",
        "🎰",
        "ピット端末",
        "退勤打刻と支払い計算を1画面で。NO. を入れて時刻確定するだけで、給与窓口は確認のみに。",
        "pages/10_ピット端末.py",
    )
with c3b:
    action_card(
        "STEP 3",
        "💰",
        "支払い計算",
        "時給×時間＋深夜＋手当＋精勤を自動計算。個別時給・タイミーにも対応。",
        "pages/3_支払い計算.py",
    )
with c3c:
    action_card(
        "STEP 3",
        "✉️",
        "封筒リスト",
        "封筒ラベルと紙幣内訳（1万円札・5千円札・千円札）を一括出力。",
        "pages/4_封筒リスト.py",
    )

# --- ④ 渡す ---
st.markdown('**STEP 4 — 渡す**')
c4a, c4b, c4c = st.columns(3)
with c4a:
    action_card(
        "STEP 4",
        "🎁",
        "個別手当",
        "言語手当・人材確保手当・リーダー手当 等を個別付与。オフレコ対応で給与窓口側のみ閲覧可。",
        "pages/11_個別手当.py",
    )
with c4b:
    action_card(
        "STEP 4",
        "📄",
        "領収書発行",
        "承認済み支払いを一括PDF化＋スタッフ向けDL用URLを発行。",
        "pages/91_領収書発行.py",
    )
with c4c:
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
    'P1 Staff Manager v3.10 · 株式会社ヒダネ'
    '</div>',
    unsafe_allow_html=True,
)
