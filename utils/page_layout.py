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
_CSS_KEY = "__p1_global_css_injected__"


def apply_global_style() -> None:
    """ページ冒頭で呼ぶ。同一スクリプト内で複数回呼んでも1回だけ注入する。"""
    if not st.session_state.get(_CSS_KEY):
        st.markdown(build_global_css(), unsafe_allow_html=True)
        st.session_state[_CSS_KEY] = True


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
