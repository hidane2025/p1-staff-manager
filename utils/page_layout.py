"""P1 Staff Manager — レイアウトヘルパー（v3.7）

【役割】
全ページで共通利用するレイアウト要素（CSS注入・ヘッダー・フローバー・KPI・カード）を
1関数1呼び出しで使えるようにする。Streamlit のネイティブ機能で実現できないものを補う。

【使い方】
    from utils.page_layout import apply_global_style, page_header, flow_bar, kpi_card

    apply_global_style()
    page_header("📋 イベント設定", "新しい大会の『型』をここで作る")
    flow_bar(active="setup", done=[])
    ...
"""

from __future__ import annotations

from typing import Iterable, Optional

import streamlit as st

from utils.design_system import COLORS, build_global_css


# ============================================================
# Global CSS injection
# ============================================================
def apply_global_style(show_quicknav: bool = True) -> None:
    """ページ冒頭で呼ぶ。グローバルCSS注入＋（任意で）サイドバーのクイックナビ描画。

    A-10 (2026-06-01): 旧版は st.session_state ガードで「1回だけ注入」していたが、
    Streamlit はリラン毎にスクリプトを再実行し、その run で再生成されない要素を
    DOM から除去する。session_state はページ遷移を跨いで永続するため、最初に
    CSS を emit したページ以外ではガードが効いて <style> が剥がれ、封筒印刷カード・
    KPIカード・iPad用大ボタン等のスタイルが崩れていた（マルチページのアンチパターン）。
    冪等かつ低コスト（約13KB）なので、毎回無条件に注入する（ui_helpers と同方式）。

    UX-1 (2026-06-01): 全管理ページが本関数を呼ぶことを利用し、サイドバー上部に
    「毎日／締め／設定」のグループ化クイックナビを描画する（既定ナビは残置）。
    16ファイルに個別実装せず一箇所で全ページに反映する。スタッフ向け公開ページ
    （領収書DL・契約署名）はサイドバー自体を隠すうえ管理リンクを出すべきでないため、
    show_quicknav=False で無効化する。
    """
    st.markdown(build_global_css(), unsafe_allow_html=True)
    if show_quicknav:
        render_quick_nav()


# クイックナビの定義。全管理ページを「優先度・業務フロー順」にグループ化し、
# 既定のフラットな自動ナビ（16項目・優先度なし）を置き換える。
# page は実在ファイル名と完全一致させること（st.page_link は不在ページで例外）。
# スタッフ向け公開ページ（9_receipt_download / 99_contract_sign）は管理ナビに含めない。
_QUICK_NAV_GROUPS = [
    ("🏠 ホーム", [
        ("🃏 トップ（今日のTo-Do）", "app.py"),
    ]),
    ("🔴 当日運用（毎日）", [
        ("🎰 ピット端末", "pages/10_ピット端末.py"),
        ("🕐 出退勤", "pages/5_出退勤.py"),
        ("💰 支払い計算", "pages/3_支払い計算.py"),
    ]),
    ("📦 締め・配布", [
        ("✉️ 封筒リスト", "pages/4_封筒リスト.py"),
        ("📄 領収書発行", "pages/91_領収書発行.py"),
        ("✍️ 契約書発行", "pages/94_契約書発行.py"),
        ("📊 精算レポート", "pages/6_精算レポート.py"),
    ]),
    ("🛠 準備・設定", [
        ("📋 イベント設定", "pages/0_イベント設定.py"),
        ("👥 スタッフ管理", "pages/1_スタッフ管理.py"),
        ("📅 シフト取込", "pages/2_シフト取込.py"),
        ("🚃 交通費", "pages/8_交通費.py"),
        ("🎁 個別手当", "pages/11_個別手当.py"),
        ("🏢 発行者設定", "pages/92_発行者設定.py"),
        ("📑 契約書テンプレ", "pages/93_契約書テンプレ.py"),
    ]),
    ("📈 集計", [
        ("📅 年間累計", "pages/7_年間累計.py"),
    ]),
]


def render_quick_nav() -> None:
    """サイドバー上部に、毎日使うページのグループ化ショートカットを描画する。

    既定のページナビ（全ページ網羅）はそのまま下に残す。本ナビは「16項目フラットで
    優先度が無い」問題を解消するための、厳選＋グループ見出し付きショートカット。
    st.page_link は存在しないページを指すと例外になるため、page は実在ファイル名と一致必須。
    """
    with st.sidebar:
        st.markdown('<div class="p1-quicknav">', unsafe_allow_html=True)
        st.markdown('<div class="p1-quicknav-title">クイックナビ</div>',
                    unsafe_allow_html=True)
        for group_label, items in _QUICK_NAV_GROUPS:
            st.markdown(
                f'<div class="p1-quicknav-group">{group_label}</div>',
                unsafe_allow_html=True,
            )
            for label, page in items:
                try:
                    st.page_link(page, label=label)
                except Exception:
                    # ページ未存在・実行コンテキスト外でも画面を壊さない
                    pass
        st.markdown('</div>', unsafe_allow_html=True)
        st.divider()


# ============================================================
# Page header
# ============================================================
def page_header(title: str, subtitle: str = "") -> None:
    """標準ページタイトル＋補助テキスト"""
    st.markdown(f"# {title}")
    if subtitle:
        st.caption(subtitle)


def section_header(title: str, help_text: str = "") -> None:
    """セクション見出し（セパレーター付き）"""
    help_html = (
        f'<p class="p1-section-help">{_escape(help_text)}</p>' if help_text else ""
    )
    st.markdown(
        f'<div class="p1-section"><h3>{_escape(title)}</h3>{help_html}</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# Progress Checklist (UX A: ホーム To-Do)
# ============================================================
def progress_checklist(items: list, show_progress_bar: bool = True) -> None:
    """ホーム画面の「今日のTo-Do」風 進捗チェックリスト

    Args:
        items: [{"label": str, "status": "done"|"warn"|"pending"|"todo",
                 "detail": str (任意), "page": str (任意/st.page_link用)}, ...]
        show_progress_bar: 上部に進捗バーを表示するか

    status:
      - "done":    ✅ 完了
      - "warn":    🟡 残作業あり（オレンジ）
      - "pending": ⏳ 待ち（青）
      - "todo":    ⬜ 未着手（グレー）
    """
    if not items:
        return

    done = sum(1 for i in items if i.get("status") == "done")
    total = len(items)

    if show_progress_bar:
        pct = int((done / total) * 100) if total else 0
        st.markdown(
            f'<div class="p1-todo-progress-wrap">'
            f'<div class="p1-todo-progress-label">'
            f'今日の進捗: <strong>{done}/{total}</strong>'
            f'</div>'
            f'<div class="p1-todo-progress-bar">'
            f'<div class="p1-todo-progress-fill" style="width:{pct}%;"></div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # アイテム描画
    icon_map = {
        "done": "✅", "warn": "🟡", "pending": "⏳", "todo": "⬜",
    }
    cls_map = {
        "done": "p1-todo-done", "warn": "p1-todo-warn",
        "pending": "p1-todo-pending", "todo": "p1-todo-todo",
    }
    for i, item in enumerate(items, 1):
        status = item.get("status", "todo")
        icon = icon_map.get(status, "⬜")
        cls = cls_map.get(status, "p1-todo-todo")
        label = _escape(item.get("label", ""))
        detail = _escape(item.get("detail", ""))
        detail_html = (
            f'<span class="p1-todo-detail">{detail}</span>' if detail else ""
        )
        st.markdown(
            f'<div class="p1-todo-row {cls}">'
            f'<span class="p1-todo-icon">{icon}</span>'
            f'<span class="p1-todo-num">{i}.</span>'
            f'<span class="p1-todo-label">{label}</span>'
            f'{detail_html}'
            f'</div>',
            unsafe_allow_html=True,
        )
        # ページリンクは Streamlit ネイティブ（HTML <a> ではnav動かない）
        page = item.get("page")
        if page:
            st.page_link(page, label=item.get("page_label", "→ このタスクを開く"))


# ============================================================
# Workflow flow bar (4-step)
# ============================================================
FLOW_STEPS = [
    ("setup",  "STEP 1", "作る",   "イベント設定"),
    ("input",  "STEP 2", "入れる", "スタッフ＋シフト"),
    ("calc",   "STEP 3", "計算",   "支払い計算"),
    ("payout", "STEP 4", "渡す",   "封筒・領収書・契約書"),
]


def flow_bar(active: str = "", done: Optional[Iterable[str]] = None) -> None:
    """画面上部の業務フローバー

    Args:
        active: 現在のステップキー（"setup"/"input"/"calc"/"payout"）
        done: 完了済みステップのキー集合
    """
    done_set = set(done or [])
    parts = ['<div class="p1-flow">']
    for key, num, label, sub in FLOW_STEPS:
        cls = "p1-flow-step"
        if key == active:
            cls += " active"
        elif key in done_set:
            cls += " done"
        parts.append(
            f'<div class="{cls}">'
            f'<span class="step-num">{num}</span>'
            f'<span class="step-label">{label}</span>'
            f'</div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ============================================================
# KPI card
# ============================================================
def kpi_card(
    label: str,
    value: str,
    detail: str = "",
    *,
    accent: bool = False,
    warning: bool = False,
) -> None:
    """単独のKPIカード（st.columns 内で使う想定）"""
    cls = "p1-kpi"
    if accent:
        cls += " accent"
    elif warning:
        cls += " warning"
    detail_html = f'<p class="p1-kpi-detail">{_escape(detail)}</p>' if detail else ""
    st.markdown(
        f'<div class="{cls}">'
        f'<p class="p1-kpi-label">{_escape(label)}</p>'
        f'<p class="p1-kpi-value">{_escape(value)}</p>'
        f'{detail_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def kpi_row(items: list) -> None:
    """KPIカードを1行に並べる。

    Args:
        items: [{"label": str, "value": str, "detail": str, "accent": bool, "warning": bool}, ...]
    """
    if not items:
        return
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        with col:
            kpi_card(
                item.get("label", ""),
                item.get("value", "—"),
                item.get("detail", ""),
                accent=item.get("accent", False),
                warning=item.get("warning", False),
            )


# ============================================================
# Status pill
# ============================================================
def pill(label: str, kind: str = "muted") -> str:
    """ステータスピル（HTML 文字列を返す。st.markdown の中でそのまま使う）

    kind: success / warning / danger / info / muted / primary
    """
    return f'<span class="p1-pill p1-pill-{kind}">{_escape(label)}</span>'


def status_pill(label: str, kind: str = "muted") -> None:
    """ステータスピルを直接表示"""
    st.markdown(pill(label, kind), unsafe_allow_html=True)


# ============================================================
# Action card (home page)
# ============================================================
def action_card(
    step_label: str,
    icon: str,
    title: str,
    desc: str,
    page_path: str,
    button_label: str = "開く →",
) -> None:
    """ホーム画面の業務アクションカード

    クリック可能領域は st.page_link が担当（HTMLの<a>がStreamlit内で機能しないため）。
    """
    st.markdown(
        f'<div class="p1-card">'
        f'<div class="p1-card-step">{_escape(step_label)}</div>'
        f'<div class="p1-card-title">{icon} {_escape(title)}</div>'
        f'<p class="p1-card-desc">{_escape(desc)}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.page_link(page_path, label=button_label)


# ============================================================
# Inline metric row (compact)
# ============================================================
def inline_metrics(items: list) -> None:
    """セクション内の補助的な数字を横一列に並べる。
    items: [(label, value), ...]
    """
    if not items:
        return
    parts = ['<div class="p1-metric-row">']
    for label, value in items:
        parts.append(
            f'<div class="p1-metric-item">'
            f'<div class="label">{_escape(label)}</div>'
            f'<div class="value">{_escape(value)}</div>'
            f'</div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ============================================================
# Friendly success / friendly error
# ============================================================
def friendly_success(message: str, *, balloons: bool = False) -> None:
    """成功時のメッセージを統一トーンで表示"""
    st.success(message, icon="✅")
    if balloons:
        st.balloons()


def friendly_error_v2(user_message: str, technical_detail: str = "",
                      next_action: str = "") -> None:
    """ユーザーフレンドリーなエラー表示（次のアクション提案付き）"""
    st.error(user_message, icon="⚠️")
    if next_action:
        st.info(f"💡 次のアクション: {next_action}", icon="🛠")
    if technical_detail:
        with st.expander("🔧 技術詳細（管理者向け）"):
            st.code(technical_detail, language="text")


# ============================================================
# Internal
# ============================================================
def _escape(s: str) -> str:
    """最低限のHTMLエスケープ（XSS対策ではなく、< > が混じった時の表示崩れ防止）"""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
