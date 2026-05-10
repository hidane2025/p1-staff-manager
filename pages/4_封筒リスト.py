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
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import (
    apply_global_style, page_header, flow_bar, section_header, kpi_row, pill,
)
from utils.admin_guard import require_admin, admin_logout_button, operator_name
apply_global_style()
hide_staff_only_pages()
# Codex P2 fix #6 (2026-05-09): 封筒明細にオフレコ手当を含む個別手当の合計が
# 印字されるため、給与窓口担当の管理者ログインを必須化。
require_admin(page_name="封筒リスト")
admin_logout_button()

page_header("✉️ 封筒リスト", "支払い計算の結果から、封筒ラベル・紙幣内訳を一括出力します。最終日の現金準備に使います。")
flow_bar(active="calc", done=["setup", "input"])

# PII閲覧監査ログ
db.log_action("view_envelope_list", "payments",
              detail="page=封筒リスト", performed_by=operator_name())

# --- イベント選択（全ページ共通） ---
st.markdown('<div class="p1-no-print">', unsafe_allow_html=True)
event_id = select_event(db.get_all_events(), "イベント選択")

# --- 設定 ---
# Codex P2 #17 fix (2026-05-09): 印刷モード ON 時は、サーバ側でそもそも
# 通常UI（出力設定・サマリ・テーブル等）を描画しない。これで visibility:hidden
# で空白ページが残る問題を構造から解消する。
_print_mode_pre = st.session_state.get("envelope_print_mode", False)

if not _print_mode_pre:
    section_header("出力設定", "端数処理と並び順を選んでください。")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        rounding = st.selectbox("端数処理", ["なし（そのまま）", "100円単位で切り上げ", "500円単位で切り上げ", "1000円単位で切り上げ"])
    with col_s2:
        sort_by = st.selectbox("並び順", ["役職 → NO.", "名前順", "金額順（高い順）"])
else:
    # 印刷モード時は前回設定値をsession_stateから引き継ぐ（デフォルト値で再構築）
    rounding = st.session_state.get("_envelope_rounding", "なし（そのまま）")
    sort_by = st.session_state.get("_envelope_sort", "役職 → NO.")
    st.info(
        "🖨 **印刷モード中** - 通常UIは非表示です。"
        "Cmd+P で印刷／PDF保存。終了時はチェックボックスをOFFに。"
    )
# 設定値を session_state に記憶（印刷モードに切り替わった後も同じ並び順を保持）
st.session_state["_envelope_rounding"] = rounding
st.session_state["_envelope_sort"] = sort_by
st.markdown('</div>', unsafe_allow_html=True)

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

# --- サマリー＋封筒リスト（印刷モード時は描画しない） ---
total_amount = sum(e["adjusted_amount"] for e in envelope_data)
all_amounts = [e["adjusted_amount"] for e in envelope_data]
total_denoms = calculate_total_denomination(all_amounts)

if not _print_mode_pre:
    section_header("銀行で用意する現金", "下記の金額・枚数を、最終日の朝までに準備します。")

    summary_items = [
        {"label": "総額", "value": f"¥{total_amount:,}", "accent": True},
        {"label": "封筒数", "value": f"{len(envelope_data)}枚"},
    ]
    if rounding_unit > 0:
        original_total = sum(p["total_amount"] for p in payments)
        summary_items.append({
            "label": "端数切り上げ分",
            "value": f"¥{total_amount - original_total:,}",
            "detail": f"単位: {rounding_unit}円",
        })
    kpi_row(summary_items)

    # 紙幣内訳（compact行）
    st.markdown("**紙幣・硬貨の必要数**")
    denom_items = sorted(total_denoms.items(), reverse=True)
    denom_cols = st.columns(min(len(denom_items), 6))
    for i, (denom, count) in enumerate(denom_items):
        with denom_cols[i % len(denom_cols)]:
            st.metric(DENOM_LABELS.get(denom, f"¥{denom}"), f"{count}枚")

    # --- 封筒リスト ---
    section_header("封筒リスト", f"{len(envelope_data)}件分の封筒情報。CSVダウンロードで明細を社内共有可能。")

    display_data = []
    for e in envelope_data:
        display_data.append({
            "NO.": e["no"],
            "名前": e["name_jp"],
            "役職": e["role"],
            "支払額": f"¥{e['adjusted_amount']:,}",
            "紙幣内訳": format_denomination(e["denomination"].bills),
            "支払状態": "支払済" if e["status"] == "paid" else "未払い",
            "領収書": "受領済" if e["receipt_received"] else "未受領",
        })

    df = pd.DataFrame(display_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

# --- 封筒ラベル印刷用 ---
if not _print_mode_pre:
    section_header("封筒ラベル（印刷用）",
                   "ブラウザの印刷機能（Cmd/Ctrl+P）で各明細をそのまま印刷できます。"
                   "1人=1ページの縦長明細で出力されます。")

# UX D2 (2026-05-09): 印刷モード切替トグル（OFF→ON で再描画して通常UIを除く）
# Codex P2 #17 fix: トグル ON 時はトグル自体だけ常時描画、他はサーバ側で制御
print_mode = st.checkbox(
    "🖨 印刷モードを表示（1人=1ページ）",
    value=_print_mode_pre,
    key="envelope_print_mode",
    help="ON にすると、画面上に印刷用の明細が全員分だけ表示されます。"
    "そのまま Cmd+P → PDF保存 で配布資料が完成します。"
    "通常UIに戻すにはチェックを外してください。",
)

if _print_mode_pre:
    # UX D2: 印刷専用レイアウト（1人=1ページ縦長）
    # サーバ側で通常UIを描画していないため、Cmd+Pで純粋に印刷カードのみ印字される
    for e in envelope_data:
        _allow_total = int(e.get("individual_allowance_total") or 0)
        _allow_row = (
            f'<tr><td>個別手当</td><td>¥{_allow_total:,}</td></tr>'
            if _allow_total else ""
        )
        st.markdown(
            f'<div class="p1-envelope-print">'
            f'<h2>P1 支払明細</h2>'
            f'<div>NO. {e["no"]}　／　{e["role"]}</div>'
            f'<div class="name-large">{e["name_jp"]} 様</div>'
            f'<div class="amount-huge">¥{e["adjusted_amount"]:,}</div>'
            f'<table>'
            f'<tr><td>基本給</td><td>¥{e["base_pay"]:,}</td></tr>'
            f'<tr><td>深夜手当</td><td>¥{e["night_pay"]:,}</td></tr>'
            f'<tr><td>交通費</td><td>¥{e["transport_total"]:,}</td></tr>'
            f'<tr><td>フロア手当</td><td>¥{e["floor_bonus_total"]:,}</td></tr>'
            f'<tr><td>MIX手当</td><td>¥{e["mix_bonus_total"]:,}</td></tr>'
            f'<tr><td>精勤手当</td><td>¥{e["attendance_bonus"]:,}</td></tr>'
            f'{_allow_row}'
            f'<tr><td><strong>合計</strong></td>'
            f'<td><strong>¥{e["adjusted_amount"]:,}</strong></td></tr>'
            f'</table>'
            f'<div style="margin-top: 16pt; font-size: 10pt;">'
            f'紙幣内訳: {format_denomination(e["denomination"].bills)}'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
else:
    # 通常モード: 折りたたみ表示
    for e in envelope_data:
        with st.expander(f"NO.{e['no']} {e['name_jp']}（{e['role']}）— ¥{e['adjusted_amount']:,}"):
            # Codex P2 fix #3: 個別手当を内訳に表示（合計との整合性）
            _allow_total = int(e.get("individual_allowance_total") or 0)
            _allow_row = (
                f"| 個別手当 | ¥{_allow_total:,} |\n" if _allow_total else ""
            )
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
{_allow_row}| **合計** | **¥{e['adjusted_amount']:,}** |

紙幣: {format_denomination(e['denomination'].bills)}
""")

# --- CSV出力（印刷モード時は描画しない） ---
if not _print_mode_pre:
    st.markdown('<div class="p1-no-print">', unsafe_allow_html=True)
    section_header("CSV出力", "経理共有用のフル明細を1ファイルでダウンロードできます。")

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
    st.markdown('</div>', unsafe_allow_html=True)
