"""P1 Staff Manager — シフト取込ページ"""

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
hide_staff_only_pages()
st.title("📅 シフト取込")

# --- イベント選択 or 作成 ---
st.subheader("1. イベントを選択")
events = db.get_all_events()

tab_select, tab_create = st.tabs(["既存イベントを選択", "新規イベント作成"])

with tab_select:
    if events:
        event_id = select_event(events, "イベント")
    else:
        st.info("イベントがありません。「新規イベント作成」タブで作成してください。")
        event_id = None

with tab_create:
    with st.form("create_event"):
        ev_name = st.text_input("イベント名", placeholder="例: P1 Nagoya 2026")
        ev_venue = st.text_input("会場", placeholder="例: 中日ホール")
        col_s, col_e = st.columns(2)
        with col_s:
            ev_start = st.date_input("開始日")
        with col_e:
            ev_end = st.date_input("終了日")
        if st.form_submit_button("作成", type="primary"):
            new_id = db.create_event(ev_name, ev_venue, str(ev_start), str(ev_end))
            st.success(f"「{ev_name}」を作成しました")
            st.rerun()

if not event_id:
    st.stop()

# --- レート設定 ---
st.divider()
st.subheader("2. 日別レート設定")

event = db.get_event_by_id(event_id)
existing_rates = db.get_event_rates(event_id)

st.markdown("各日の時給・手当を設定します。設定しない日はデフォルト値（時給¥1,500 / 深夜¥1,875）が適用されます。")

with st.form("rate_form"):
    st.markdown("**日別設定**")

    rate_dates = existing_rates if existing_rates else []
    if not rate_dates:
        st.info("シフトを取り込むと、自動で日付が設定されます。または手動で入力してください。")

    manual_date = st.text_input("日付を追加（YYYY-MM-DD）", placeholder="例: 2025-12-31")

    col_r1, col_r2, col_r3, col_r4 = st.columns(4)
    with col_r1:
        r_hourly = st.number_input("通常時給 (円)", value=1500, step=100)
    with col_r2:
        r_night = st.number_input("深夜時給 (円)", value=1875, step=100)
    with col_r3:
        r_transport = st.number_input("交通費 (円/日)", value=1000, step=100)
    with col_r4:
        r_floor = st.number_input("フロア手当 (円/日)", value=3000, step=500)

    r_mix = st.number_input("MIX手当 (円/日)", value=1500, step=500)
    r_label = st.selectbox("日の種類", ["regular", "premium"])

    if st.form_submit_button("レート保存"):
        if manual_date:
            db.set_event_rate(event_id, manual_date, r_hourly, r_night,
                              r_transport, r_floor, r_mix, r_label)
            st.success(f"{manual_date} のレートを保存しました")
            st.rerun()
        else:
            st.error("日付を入力してください")

# 現在のレート表示
current_rates = db.get_event_rates(event_id)
if current_rates:
    st.markdown("**設定済みレート:**")
    rate_df = pd.DataFrame(current_rates)
    display_cols = ["date", "date_label", "hourly_rate", "night_rate",
                    "transport_allowance", "floor_bonus", "mix_bonus"]
    available_cols = [c for c in display_cols if c in rate_df.columns]
    st.dataframe(rate_df[available_cols], use_container_width=True, hide_index=True)

# --- CSV取込 ---
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

year_input = st.number_input("年（12月の年を入力）", value=2025, step=1,
                              help="12/29は入力年、1/4は翌年として処理します")

if uploaded:
    content = uploaded.read()
    parsed = parse_shift_csv(content, year=year_input)

    st.success(f"パース完了: {len(parsed['staff'])}名のスタッフ / {len(parsed['dates'])}日間 / {len(parsed['shifts'])}シフト")

    # プレビュー
    if parsed["staff"]:
        st.markdown("**スタッフプレビュー:**")
        staff_df = pd.DataFrame(parsed["staff"])
        st.dataframe(staff_df, use_container_width=True, hide_index=True)

    if parsed["shifts"]:
        st.markdown("**シフトプレビュー（先頭20件）:**")
        shift_df = pd.DataFrame(parsed["shifts"][:20])
        st.dataframe(shift_df, use_container_width=True, hide_index=True)

    # 取り込み実行
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

        st.success(f"取り込み完了: {imported_staff}名のスタッフ / {imported_shifts}シフトを登録")
        st.balloons()
        st.rerun()

# --- 現在のシフト表示 ---
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
