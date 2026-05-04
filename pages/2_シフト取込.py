"""P1 Staff Manager — シフト取込ページ

役割: 完成済みイベント（基本情報・レート設定済み）に対してシフトCSVを流し込む。
イベント本体の作成・編集は pages/0_イベント設定.py に集約。
"""

import streamlit as st
import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.shift_parser import parse_shift_csv
from utils.calculator import parse_shift_time
from utils.event_selector import select_event

st.set_page_config(page_title="シフト取込", page_icon="📅", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style, page_header, flow_bar
apply_global_style()
hide_staff_only_pages()

page_header("📅 シフト取込", "完成済みイベントにシフトCSVを取り込む。新規イベントは『📋 イベント設定』で先に作成してください。")
flow_bar(active="input", done=["setup"])


# ============================================================
# 1. イベント選択
# ============================================================
st.subheader("1. イベントを選択")
events = db.get_all_events()

if not events:
    st.warning(
        "⚠️ イベントがまだありません。先に **「📋 イベント設定」** ページで "
        "イベントを作成してください。"
    )
    st.page_link("pages/0_イベント設定.py", label="📋 イベント設定を開く", icon="📋")
    st.stop()

event_id = select_event(events, "対象イベント")
if not event_id:
    st.stop()

event = db.get_event_by_id(event_id)
if event:
    st.write(
        f"📍 **{event.get('name')}**　"
        f"会場: {event.get('venue', '—')}　"
        f"期間: {event.get('start_date', '—')} 〜 {event.get('end_date', '—')}"
    )


# ============================================================
# 2. 現行レート（読み取り専用） — 編集はイベント設定で
# ============================================================
st.divider()
st.subheader("2. 設定済みレートの確認")

current_rates = db.get_event_rates(event_id)
if current_rates:
    rate_df = pd.DataFrame(current_rates)
    display_cols = ["date", "date_label", "hourly_rate", "night_rate",
                    "transport_allowance", "floor_bonus", "mix_bonus"]
    available = [c for c in display_cols if c in rate_df.columns]
    st.dataframe(rate_df[available], use_container_width=True, hide_index=True)
    st.caption("レート編集は『📋 イベント設定』タブ『既存編集』で行ってください。")
else:
    st.info(
        "ℹ️ レート未設定です。シフトを取り込むと日付に対してデフォルト "
        "（時給¥1,500 / 深夜¥1,875）で自動補完されます。"
        "プリセットを適用するには『📋 イベント設定』を使ってください。"
    )
    st.page_link("pages/0_イベント設定.py", label="📋 レート設定はこちら", icon="📋")


# ============================================================
# 3. シフトCSV取込
# ============================================================
st.divider()
st.subheader("3. シフト表を取り込み")

st.markdown("""
**対応フォーマット:** CSV / TSV（Googleスプレッドシートからダウンロード可）

**必要な列:**
- A列: 役職（TD / Floor / Dealer 等）
- C列: NO.
- D列: 名前（日本語）
- E列: 名前（英語）
- F列以降: 日付ごとの時間（例: `13:00~23:00`）。 `×` は休み。
""")

uploaded = st.file_uploader("CSVまたはTSVファイル", type=["csv", "tsv", "txt"])

# 年指定: イベント開始年を初期値に
default_year = 2026
if event and event.get("start_date"):
    try:
        default_year = int(event["start_date"][:4])
    except Exception:
        pass

year_input = st.number_input(
    "年（最初の月の年を入力）",
    value=default_year, step=1,
    help="例: 12/29は入力年、1/4は翌年として処理します。8月開催なら開催年。",
)

if uploaded:
    # P2#8 (2026-05-04): アップロードサイズの上限チェック（5MB）
    MAX_UPLOAD_SIZE = 5 * 1024 * 1024
    if uploaded.size > MAX_UPLOAD_SIZE:
        st.error(
            f"❌ ファイルが大きすぎます（{uploaded.size / 1024 / 1024:.1f}MB）。"
            f"上限は {MAX_UPLOAD_SIZE / 1024 / 1024:.0f}MB です。"
        )
        st.stop()
    content = uploaded.read()
    parsed = parse_shift_csv(content, year=year_input)

    st.success(
        f"パース完了: {len(parsed['staff'])}名のスタッフ / "
        f"{len(parsed['dates'])}日間 / {len(parsed['shifts'])}シフト"
    )

    # プレビュー
    if parsed["staff"]:
        st.markdown("**スタッフプレビュー:**")
        st.dataframe(pd.DataFrame(parsed["staff"]), use_container_width=True, hide_index=True)

    if parsed["shifts"]:
        st.markdown("**シフトプレビュー（先頭20件）:**")
        st.dataframe(pd.DataFrame(parsed["shifts"][:20]), use_container_width=True, hide_index=True)

    if st.button("🚀 取り込み実行", type="primary"):
        imported_staff = 0
        imported_shifts = 0

        for s in parsed["staff"]:
            db.find_or_create_staff(s["no"], s["name_jp"], s["name_en"], s["role"])
            imported_staff += 1

        for shift in parsed["shifts"]:
            staff_id = db.find_or_create_staff(shift["no"], shift["name_jp"], role=shift["role"])
            time_parsed = parse_shift_time(shift["time_range"])
            if time_parsed:
                start_min, end_min = time_parsed
                start_str = f"{start_min // 60:02d}:{start_min % 60:02d}"
                end_str = f"{end_min // 60:02d}:{end_min % 60:02d}"
                db.upsert_shift(event_id, staff_id, shift["date"], start_str, end_str)
                imported_shifts += 1

        # 日付からレートを自動設定（未設定の日のみ）
        existing_rate_dates = {r["date"] for r in db.get_event_rates(event_id)}
        for date in parsed["dates"]:
            if date not in existing_rate_dates:
                db.set_event_rate(event_id, date)

        st.success(
            f"取り込み完了: {imported_staff}名のスタッフ / {imported_shifts}シフトを登録"
        )
        st.balloons()
        st.rerun()


# ============================================================
# 4. 取り込み済みシフト
# ============================================================
st.divider()
st.subheader("4. 取り込み済みシフト")

shifts = db.get_shifts_for_event(event_id)
if shifts:
    st.write(f"合計: {len(shifts)} シフト")
    shift_display = pd.DataFrame(shifts)
    display_cols = ["name_jp", "role", "no", "date", "planned_start", "planned_end", "status"]
    available = [c for c in display_cols if c in shift_display.columns]
    st.dataframe(shift_display[available], use_container_width=True, hide_index=True)
else:
    st.info("シフトがまだ取り込まれていません。")
