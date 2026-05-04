"""P1 Staff Manager — デザインシステム（v3.7）

【役割】
全ページで使う色・タイポグラフィ・コンポーネントスタイルを一元管理する。
Streamlit の制約下で「実務SaaSとして見やすく・押しやすく・印刷もできる」を目指す。

【方針】
- 既存のブランド色 #006B5A（緑）を主軸として維持
- ヒダネ橙 #F28C28 は「ここが大事」のシグナル用に少しだけ
- 明背景＋強コントラストで眼精疲労を最小化（毎日使うため）
- カード・余白・色階調で情報のヒエラルキーを作る
- 印刷／iPadも崩れないよう対応
"""

from __future__ import annotations


# ============================================================
# Color tokens
# ============================================================
COLORS: dict = {
    # Brand
    "primary": "#006B5A",          # メインの緑
    "primary_dark": "#00513F",     # ホバー
    "primary_light": "#E8F4F0",    # アクセント背景
    "primary_lighter": "#F4FAF8",  # ごく薄い背景
    "accent": "#F28C28",           # ヒダネ橙（「重要」のみ）
    "accent_dark": "#D9751A",

    # Semantic
    "success": "#16A34A",
    "success_bg": "#DCFCE7",
    "warning": "#D97706",
    "warning_bg": "#FEF3C7",
    "danger": "#DC2626",
    "danger_bg": "#FEE2E2",
    "info": "#0284C7",
    "info_bg": "#E0F2FE",

    # Neutral
    "bg": "#F8FAFC",
    "surface": "#FFFFFF",
    "surface_muted": "#F1F5F9",
    "text": "#0F172A",
    "text_secondary": "#475569",
    "text_muted": "#94A3B8",
    "border": "#E2E8F0",
    "border_strong": "#CBD5E1",
}


# ============================================================
# Typography stack
# ============================================================
FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Hiragino Sans", '
    '"Hiragino Kaku Gothic ProN", "Yu Gothic UI", "Meiryo", '
    '"Helvetica Neue", Arial, sans-serif'
)
FONT_MONO = (
    '"SF Mono", "Menlo", "Consolas", "Liberation Mono", '
    '"Courier New", monospace'
)


# ============================================================
# Global CSS
# ============================================================
def build_global_css() -> str:
    c = COLORS
    return f"""
<style>
/* ============ Base ============ */
.stApp {{
    background-color: {c["bg"]};
}}

html, body, [data-testid="stAppViewContainer"], [class*="css"] {{
    font-family: {FONT_STACK};
}}

/* ============ Typography ============ */
h1, h2, h3, h4 {{
    color: {c["text"]};
    letter-spacing: -0.01em;
}}
h1 {{ font-weight: 700; letter-spacing: -0.02em; }}
h2 {{ font-weight: 700; }}
h3 {{ font-weight: 600; }}

/* Streamlit captions a bit darker for readability */
[data-testid="stCaptionContainer"] {{ color: {c["text_secondary"]} !important; }}

/* ============ Sidebar ============ */
[data-testid="stSidebar"] {{
    background-color: {c["surface"]};
    border-right: 1px solid {c["border"]};
}}
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {{
    border-radius: 6px;
    margin: 1px 0;
}}
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {{
    background-color: {c["primary_lighter"]};
}}
/* セクション見出し（utils/page_layout の sidebar_section_label が出力） */
.p1-sidebar-section {{
    font-size: 11px;
    font-weight: 700;
    color: {c["text_muted"]};
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 12px 12px 4px;
    margin-top: 4px;
}}

/* ============ Buttons ============ */
button[kind="primary"], button[data-testid="baseButton-primary"] {{
    background: {c["primary"]} !important;
    border-color: {c["primary"]} !important;
    box-shadow: 0 1px 0 rgba(0,0,0,0.04);
}}
button[kind="primary"]:hover, button[data-testid="baseButton-primary"]:hover {{
    background: {c["primary_dark"]} !important;
    border-color: {c["primary_dark"]} !important;
}}
button[kind="secondary"]:hover, button[data-testid="baseButton-secondary"]:hover {{
    border-color: {c["primary"]} !important;
    color: {c["primary"]} !important;
}}

/* ============ Status pill ============ */
.p1-pill {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 9999px;
    font-size: 11.5px;
    font-weight: 600;
    line-height: 1.4;
    letter-spacing: 0.02em;
    border: 1px solid transparent;
}}
.p1-pill-success {{ background: {c["success_bg"]}; color: #166534; border-color: #BBF7D0; }}
.p1-pill-warning {{ background: {c["warning_bg"]}; color: #92400E; border-color: #FDE68A; }}
.p1-pill-danger  {{ background: {c["danger_bg"]};  color: #991B1B; border-color: #FECACA; }}
.p1-pill-info    {{ background: {c["info_bg"]};    color: #075985; border-color: #BAE6FD; }}
.p1-pill-muted   {{ background: {c["surface_muted"]}; color: {c["text_secondary"]}; border-color: {c["border"]}; }}
.p1-pill-primary {{ background: {c["primary_light"]}; color: {c["primary_dark"]}; border-color: #B7E0D2; }}

/* ============ KPI card ============ */
.p1-kpi {{
    background: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 12px;
    padding: 16px 20px;
    height: 100%;
}}
.p1-kpi-label {{
    font-size: 12px;
    color: {c["text_secondary"]};
    font-weight: 500;
    margin: 0 0 6px;
    letter-spacing: 0.02em;
}}
.p1-kpi-value {{
    font-size: 28px;
    color: {c["text"]};
    font-weight: 700;
    margin: 0 0 4px;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
}}
.p1-kpi-detail {{
    font-size: 12px;
    color: {c["text_secondary"]};
    margin: 0;
    line-height: 1.4;
}}
.p1-kpi.accent {{
    border-color: {c["primary"]};
    background: linear-gradient(135deg, {c["primary_light"]} 0%, {c["surface"]} 60%);
}}
.p1-kpi.accent .p1-kpi-value {{ color: {c["primary_dark"]}; }}
.p1-kpi.warning {{ border-color: {c["warning"]}; }}
.p1-kpi.warning .p1-kpi-value {{ color: {c["warning"]}; }}

/* ============ Action card (home) ============ */
.p1-card {{
    background: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 12px;
    padding: 18px 20px 14px;
    height: 100%;
    transition: border-color 0.15s, box-shadow 0.15s;
}}
.p1-card:hover {{
    border-color: {c["primary"]};
    box-shadow: 0 1px 4px rgba(0, 107, 90, 0.08);
}}
.p1-card-step {{
    font-size: 10.5px;
    color: {c["primary"]};
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 4px;
}}
.p1-card-title {{
    font-size: 16px;
    color: {c["text"]};
    font-weight: 600;
    margin: 0 0 6px;
    line-height: 1.3;
}}
.p1-card-desc {{
    font-size: 13px;
    color: {c["text_secondary"]};
    line-height: 1.5;
    margin: 0 0 4px;
}}

/* ============ Flow bar ============ */
.p1-flow {{
    display: flex;
    gap: 0;
    margin: 8px 0 22px;
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid {c["border"]};
    background: {c["surface"]};
    box-shadow: 0 1px 0 rgba(15, 23, 42, 0.02);
}}
.p1-flow-step {{
    flex: 1;
    padding: 11px 12px 10px;
    font-size: 13px;
    color: {c["text_muted"]};
    text-align: center;
    border-right: 1px solid {c["border"]};
    position: relative;
    line-height: 1.3;
}}
.p1-flow-step:last-child {{ border-right: none; }}
.p1-flow-step .step-num {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.05em;
    display: block;
    margin-bottom: 1px;
}}
.p1-flow-step.active {{
    background: {c["primary"]};
    color: #fff;
}}
.p1-flow-step.active .step-num {{ color: #fff; opacity: 0.85; }}
.p1-flow-step.active .step-label {{ font-weight: 600; }}
.p1-flow-step.done {{
    background: {c["primary_light"]};
    color: {c["primary_dark"]};
}}
.p1-flow-step.done .step-num {{ color: {c["primary"]}; }}

/* ============ Section header ============ */
.p1-section {{
    margin: 28px 0 12px;
    padding-bottom: 6px;
    border-bottom: 1px solid {c["border"]};
}}
.p1-section h2,
.p1-section h3 {{
    margin: 0 0 4px;
}}
.p1-section .p1-section-help {{
    font-size: 13px;
    color: {c["text_secondary"]};
    margin: 0;
}}

/* ============ Inline metric (compact) ============ */
.p1-metric-row {{
    display: flex;
    gap: 28px;
    flex-wrap: wrap;
    margin: 12px 0;
    padding: 14px 18px;
    background: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
}}
.p1-metric-item .label {{
    font-size: 11.5px;
    color: {c["text_muted"]};
    font-weight: 500;
    letter-spacing: 0.04em;
}}
.p1-metric-item .value {{
    font-size: 18px;
    color: {c["text"]};
    font-weight: 700;
    margin-top: 2px;
    font-variant-numeric: tabular-nums;
}}

/* ============ Streamlit native polish ============ */
[data-testid="stMetricValue"] {{
    font-size: 24px !important;
    font-variant-numeric: tabular-nums;
}}
[data-testid="stMetricLabel"] {{
    font-size: 12px !important;
    color: {c["text_secondary"]} !important;
}}

/* DataFrame: tighter look */
[data-testid="stDataFrame"] {{
    border-radius: 10px;
    border: 1px solid {c["border"]};
}}

/* Tabs: emphasize active */
[data-baseweb="tab-list"] [aria-selected="true"] {{
    color: {c["primary"]} !important;
}}
[data-baseweb="tab-highlight"] {{
    background-color: {c["primary"]} !important;
}}

/* Forms: tighter spacing */
.stForm {{ background: {c["surface"]}; border: 1px solid {c["border"]}; border-radius: 10px; padding: 18px; }}

/* Expander: subtle */
.streamlit-expanderHeader {{ font-weight: 600; }}

/* ============ iPad / Tablet ============ */
@media (max-width: 1280px) {{
    .p1-card {{ padding: 14px 16px 10px; }}
    .p1-kpi-value {{ font-size: 24px; }}
}}
@media (max-width: 1024px) {{
    button {{ min-height: 44px; }}
    .p1-flow-step {{ padding: 9px 6px 8px; font-size: 12px; }}
    .p1-flow-step .step-num {{ font-size: 10px; }}
    .p1-metric-row {{ gap: 16px; padding: 12px 14px; }}
    .p1-metric-item .value {{ font-size: 16px; }}
}}

/* ============ Print ============ */
@media print {{
    [data-testid="stSidebar"],
    [data-testid="stHeader"],
    [data-testid="stToolbar"] {{
        display: none !important;
    }}
    .stApp {{ background: white !important; }}
    .p1-no-print {{ display: none !important; }}
    .p1-flow, .p1-card {{ break-inside: avoid; }}
    h1 {{ font-size: 20pt; }}
    h2 {{ font-size: 14pt; }}
    h3 {{ font-size: 12pt; }}
}}

/* ============ Tighten default Streamlit margins ============ */
.block-container {{ padding-top: 2rem; padding-bottom: 4rem; }}
</style>
"""
