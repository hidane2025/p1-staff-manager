"""P1 Staff Manager — 出退勤管理（例外ベース）

原則：シフト通り＝デフォルト。例外だけ記録する。
- 「全員出勤」→ 来てない人だけ×
- 退勤は予定時刻で自動確定 → 延長/早退だけ修正
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.event_selector import select_event

st.set_page_config(page_title="出退勤", page_icon="🕐", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style, page_header, flow_bar
apply_global_style()
hide_staff_only_pages()

page_header("🕐 出退勤管理", "シフト通り＝デフォルト。例外（欠勤・遅刻・延長・早退）だけ記録します。")
flow_bar(active="input", done=["setup"])

# --- イベント・日付選択（全ページ共通のsession_state共有） ---
event_id = select_event(db.get_all_events(), "イベント")

rates = db.get_event_rates(event_id)
date_options = [r["date"] for r in rates]
if not date_options:
    st.warning("レートが設定されていません。")
    st.stop()

selected_date = st.selectbox("日付", date_options)

# --- 当日のシフト取得 ---
shifts = db.get_shifts_for_event(event_id, date=selected_date)
if not shifts:
    st.info(f"{selected_date} のシフトはありません。")
    st.stop()

# --- サマリー ---
total = len(shifts)
checked_in = sum(1 for s in shifts if s["status"] in ("checked_in", "checked_out"))
checked_out = sum(1 for s in shifts if s["status"] == "checked_out")
absent = sum(1 for s in shifts if s["status"] == "absent")
exceptions = sum(1 for s in shifts if s.get("actual_start") or s.get("actual_end"))

confirmed = sum(1 for s in shifts if s["status"] in ("checked_in", "checked_out"))
col1, col2, col3, col4 = st.columns(4)
col1.metric("予定人数", f"{total}名")
col2.metric("出勤確定", f"{confirmed}名")
col3.metric("欠勤", f"{absent}名", delta_color="inverse")
col4.metric("未確定", f"{total - confirmed - absent}名")

st.divider()

# ============================================================
# セクション1: 一括操作（1日5分で終わる）
# ============================================================
st.subheader("① 一括操作")

# --- 全員出勤の時刻フィルタ ---
today_str = datetime.now().strftime("%Y-%m-%d")
is_today = (selected_date == today_str)
now_str = datetime.now().strftime("%H:%M")

scheduled_shifts = [s for s in shifts if s["status"] == "scheduled"]

if is_today:
    # 当日: 現在時刻以前に出勤予定のスタッフのみ
    eligible_shifts = [
        s for s in scheduled_shifts
        if s.get("planned_start", "99:99") <= now_str
    ]
    btn_label = f"✅ 現在時刻までの予定者を出勤（{len(eligible_shifts)}名）"
else:
    # 過去・未来の日付: 全員対象
    eligible_shifts = scheduled_shifts
    btn_label = f"✅ 全員出勤（{len(eligible_shifts)}名）"

eligible_count = len(eligible_shifts)

col_bulk1, col_bulk2, col_bulk3 = st.columns(3)

with col_bulk1:
    if st.button(btn_label, type="primary", use_container_width=True):
        if eligible_count == 0:
            st.info("対象のスタッフがいません（全員出勤済みまたは欠勤）")
        else:
            client = db.get_client()
            for s in eligible_shifts:
                client.table("p1_shifts").update({
                    "actual_start": s["planned_start"],
                    "status": "checked_in",
                }).eq("id", s["id"]).execute()
            st.success(f"{eligible_count}名を出勤にしました（予定開始が {now_str} 以前）")
            st.rerun()

with col_bulk2:
    if st.button("🔴 全員退勤（予定時刻で確定）", use_container_width=True):
        client = db.get_client()
        for s in shifts:
            if s["status"] in ("checked_in", "scheduled"):
                actual_end = s.get("actual_end") or s["planned_end"]
                client.table("p1_shifts").update({
                    "actual_end": actual_end,
                    "actual_start": s.get("actual_start") or s["planned_start"],
                    "status": "checked_out",
                }).eq("id", s["id"]).execute()
        st.success("全員を予定時刻で退勤確定しました")
        st.rerun()

with col_bulk3:
    if "confirm_reset" not in st.session_state:
        st.session_state["confirm_reset"] = False
    if not st.session_state["confirm_reset"]:
        if st.button("🔄 リセット", use_container_width=True):
            st.session_state["confirm_reset"] = True
            st.rerun()
    else:
        st.error("⚠️ 全員の出退勤データが消えます")
        col_yes, col_no = st.columns(2)
        if col_yes.button("はい、リセットする", type="primary"):
            client = db.get_client()
            for s in shifts:
                client.table("p1_shifts").update({
                    "actual_start": None,
                    "actual_end": None,
                    "status": "scheduled",
                }).eq("id", s["id"]).execute()
            st.session_state["confirm_reset"] = False
            st.success("全員のステータスをリセットしました")
            st.rerun()
        if col_no.button("キャンセル"):
            st.session_state["confirm_reset"] = False
            st.rerun()

# ============================================================
# セクション2: 例外だけ記録
# ============================================================
st.divider()
st.subheader("② 例外を記録（来てない人・時間が違う人だけ）")

# タブで操作を分ける（凍結退勤を最初＝最終日の主要操作）
tab_freeze, tab_absent, tab_late, tab_overtime, tab_early = st.tabs([
    "🧊 凍結退勤（一括）", "❌ 欠勤", "⏰ 遅刻", "⏩ 延長（残業）", "⏪ 早退"
])

# スタッフ選択肢を生成
staff_options = {
    f"NO.{s['no']} {s['name_jp']} ({s['role']}) [{s['planned_start']}〜{s['planned_end']}]": s
    for s in shifts
}

with tab_absent:
    st.markdown("来なかった人を選んで「欠勤にする」を押す")
    absent_staff = st.multiselect(
        "欠勤者を選択（複数可）",
        list(staff_options.keys()),
        key="absent_select"
    )
    if st.button("❌ 選択した人を欠勤にする", key="mark_absent"):
        if absent_staff:
            for name in absent_staff:
                s = staff_options[name]
                db.mark_absent(s["id"])
            st.success(f"{len(absent_staff)}名を欠勤にしました")
            st.rerun()

with tab_late:
    st.markdown("遅刻した人の実際の到着時刻を記録")
    late_staff = st.selectbox("スタッフ", list(staff_options.keys()), key="late_select")
    if late_staff:
        s = staff_options[late_staff]
        st.info(f"予定出勤: {s['planned_start']}")
        col_lh, col_lm = st.columns(2)
        with col_lh:
            late_hour = st.number_input("時", min_value=0, max_value=29, value=int(s['planned_start'].split(':')[0]), key="late_hour")
        with col_lm:
            late_min = st.selectbox("分", [0, 15, 30, 45], key="late_min")
        if st.button("⏰ 遅刻を記録", key="mark_late"):
            time_str = f"{late_hour:02d}:{late_min:02d}"
            db.checkin_staff(s["id"], time_str)
            st.success(f"{s['name_jp']} の到着時刻を {time_str} に記録しました（予定: {s['planned_start']}）")
            st.rerun()

with tab_overtime:
    st.markdown("予定より遅くまで働いた人の実際の退勤時刻を記録")
    ot_staff = st.selectbox("スタッフ", list(staff_options.keys()), key="ot_select")
    if ot_staff:
        s = staff_options[ot_staff]
        st.info(f"予定退勤: {s['planned_end']}")
        ot_hour = st.number_input("実際の退勤（時）", min_value=0, max_value=29, value=int(s['planned_end'].split(':')[0]) + 1, key="ot_hour")
        ot_min = st.selectbox("実際の退勤（分）", [0, 15, 30, 45], key="ot_min")
        if st.button("⏩ 延長を記録", key="mark_ot"):
            time_str = f"{ot_hour:02d}:{ot_min:02d}"
            db.checkout_staff(s["id"], time_str)
            st.success(f"{s['name_jp']} の退勤を {time_str} に記録しました（予定: {s['planned_end']}）")
            st.rerun()

with tab_early:
    st.markdown("予定より早く帰った人の実際の退勤時刻を記録")
    early_staff = st.selectbox("スタッフ", list(staff_options.keys()), key="early_select")
    if early_staff:
        s = staff_options[early_staff]
        st.info(f"予定退勤: {s['planned_end']}")
        col_eh, col_em = st.columns(2)
        with col_eh:
            early_hour = st.number_input("時", min_value=0, max_value=29, value=max(0, int(s['planned_end'].split(':')[0]) - 1), key="early_hour")
        with col_em:
            early_min = st.selectbox("分", [0, 15, 30, 45], key="early_min")
        if st.button("⏪ 早退を記録", key="mark_early"):
            time_str = f"{early_hour:02d}:{early_min:02d}"
            db.checkout_staff(s["id"], time_str)
            st.success(f"{s['name_jp']} の退勤を {time_str} に記録しました（予定: {s['planned_end']}）")
            st.rerun()

with tab_freeze:
    st.markdown("凍結（フリーズ）対応：複数スタッフを同一時刻で一括退勤させる")
    freeze_candidates = {
        f"NO.{s['no']} {s['name_jp']} ({s['role']}) [{s['planned_start']}〜{s['planned_end']}]": s
        for s in shifts
        if s["status"] in ("checked_in", "scheduled")
    }
    if not freeze_candidates:
        st.info("一括退勤の対象（出勤中・未確定）がいません")
    else:
        freeze_selected = st.multiselect(
            "退勤させるスタッフを選択（複数可）",
            list(freeze_candidates.keys()),
            key="freeze_select",
        )
        col_fh, col_fm = st.columns(2)
        with col_fh:
            freeze_hour = st.number_input("退勤時刻（時）", min_value=0, max_value=29, value=int(datetime.now().strftime("%H")), key="freeze_hour")
        with col_fm:
            freeze_min = st.selectbox("退勤時刻（分）", [0, 15, 30, 45], key="freeze_min")
        if st.button("🧊 凍結退勤を実行", key="exec_freeze", type="primary"):
            if freeze_selected:
                freeze_time = f"{freeze_hour:02d}:{freeze_min:02d}"
                freeze_ids = [freeze_candidates[name]["id"] for name in freeze_selected]
                affected_staff = db.bulk_checkout(freeze_ids, freeze_time, event_id)
                # 影響を受けたスタッフの支払いを「未承認」に戻して再計算を促す
                reset_count = 0
                protected_count = 0
                for staff_id in affected_staff:
                    if db.reset_payment_to_pending(event_id, staff_id,
                                                    reason=f"凍結退勤 {freeze_time}"):
                        reset_count += 1
                    else:
                        # paid の場合または支払いレコードなし
                        client_q = db.get_client().table("p1_payments").select(
                            "status").eq("event_id", event_id).eq(
                            "staff_id", staff_id).execute().data
                        if client_q and client_q[0].get("status") == "paid":
                            protected_count += 1
                st.success(f"{len(freeze_ids)}名を {freeze_time} で一括退勤しました")
                if reset_count:
                    st.info(
                        f"💡 {reset_count}名の支払いを未承認に戻しました。"
                        "「💰 支払い計算」ページで再計算してください。"
                    )
                if protected_count:
                    st.warning(
                        f"⚠️ {protected_count}名はすでに支払済みのため再計算されません（保護）。"
                        "差額は小口精算で対応してください。"
                    )
                st.rerun()
            else:
                st.warning("スタッフを選択してください")

# ============================================================
# セクション2-B: 当日スタッフ追加
# ============================================================
st.divider()
st.subheader("② - B 当日スタッフ追加")

all_staff = db.get_all_staff()
add_mode = st.radio("追加方法", ["既存スタッフから選択", "新規スタッフを作成"], horizontal=True, key="add_mode")

if add_mode == "既存スタッフから選択":
    if not all_staff:
        st.info("登録済みスタッフがいません。新規作成してください。")
    else:
        staff_select_options = {
            f"NO.{s['no']} {s['name_jp']} ({s['role']})": s
            for s in all_staff
        }
        selected_add_staff = st.selectbox(
            "スタッフを選択",
            list(staff_select_options.keys()),
            key="add_staff_select",
        )
        add_staff_data = staff_select_options[selected_add_staff] if selected_add_staff else None
else:
    col_new1, col_new2 = st.columns(2)
    with col_new1:
        new_no = st.text_input("スタッフNO", key="new_staff_no")
        new_name_jp = st.text_input("名前（日本語）", key="new_staff_name_jp")
    with col_new2:
        new_name_en = st.text_input("名前（英語）", value="", key="new_staff_name_en")
        new_role = st.selectbox("役職", ["Dealer", "Floor", "Chip", "Other"], key="new_staff_role")
    add_staff_data = None

col_sh, col_sm, col_eh2, col_em2 = st.columns(4)
with col_sh:
    add_start_hour = st.number_input("開始（時）", min_value=0, max_value=29, value=18, key="add_start_h")
with col_sm:
    add_start_min = st.selectbox("開始（分）", [0, 15, 30, 45], key="add_start_m")
with col_eh2:
    add_end_hour = st.number_input("終了（時）", min_value=0, max_value=29, value=23, key="add_end_h")
with col_em2:
    add_end_min = st.selectbox("終了（分）", [0, 15, 30, 45], key="add_end_m")

if st.button("➕ 当日シフトに追加", key="exec_add_staff", type="primary"):
    planned_start = f"{add_start_hour:02d}:{add_start_min:02d}"
    planned_end = f"{add_end_hour:02d}:{add_end_min:02d}"

    if add_mode == "既存スタッフから選択":
        if add_staff_data:
            db.upsert_shift(event_id, add_staff_data["id"], selected_date, planned_start, planned_end)
            st.success(f"{add_staff_data['name_jp']} を {planned_start}〜{planned_end} で追加しました")
            st.rerun()
        else:
            st.warning("スタッフを選択してください")
    else:
        if not new_no or not new_name_jp:
            st.warning("スタッフNOと名前（日本語）は必須です")
        else:
            staff_row = db.find_or_create_staff(new_no, new_name_jp, new_name_en, new_role)
            new_staff_id = staff_row["id"] if isinstance(staff_row, dict) else staff_row
            db.upsert_shift(event_id, new_staff_id, selected_date, planned_start, planned_end)
            st.success(f"{new_name_jp} を {planned_start}〜{planned_end} で追加しました")
            st.rerun()

# ============================================================
# セクション3: 当日の状況一覧
# ============================================================
st.divider()
st.subheader("③ 本日の状況一覧")

# 再取得
shifts = db.get_shifts_for_event(event_id, date=selected_date)

STATUS_DISPLAY = {
    "scheduled": "⬜ 未確定",
    "checked_in": "🟢 出勤中",
    "checked_out": "✅ 退勤済",
    "absent": "❌ 欠勤",
}

display = []
for s in shifts:
    planned = f"{s['planned_start']}〜{s['planned_end']}"
    actual_start = s.get("actual_start") or "—"
    actual_end = s.get("actual_end") or "—"

    # 差異検出
    note = ""
    if s["status"] == "absent":
        note = "欠勤"
    elif s.get("actual_start") and s.get("planned_start") and s["actual_start"] > s["planned_start"]:
        note = f"⚠️ 遅刻（{s['actual_start']}着）"
    elif s.get("actual_end") and s.get("planned_end") and s["actual_end"] > s["planned_end"]:
        note = f"⏩ 延長（{s['actual_end']}退勤）"
    elif s.get("actual_end") and s.get("planned_end") and s["actual_end"] < s["planned_end"]:
        note = f"⏪ 早退（{s['actual_end']}退勤）"

    display.append({
        "NO.": s["no"],
        "名前": s["name_jp"],
        "役職": s["role"],
        "予定": planned,
        "実到着": actual_start,
        "実退勤": actual_end,
        "状態": STATUS_DISPLAY.get(s["status"], s["status"]),
        "例外": note,
        "MIX": bool(s.get("is_mix", 0)),
        "備考": s.get("notes") or "",
        "_shift_id": s["id"],
    })

df = pd.DataFrame(display)

# MIX・備考を編集可能にしたテーブル
edited_df = st.data_editor(
    df,
    use_container_width=True,
    hide_index=True,
    height=600,
    disabled=["NO.", "名前", "役職", "予定", "実到着", "実退勤", "状態", "例外", "_shift_id"],
    column_config={
        "MIX": st.column_config.CheckboxColumn("MIX", default=False),
        "備考": st.column_config.TextColumn("備考", help="イレギュラー対応等を自由入力"),
        "_shift_id": None,
    },
    key="shift_table",
)

# 変更検出・保存（MIXと備考）
if not df.empty and not edited_df.empty:
    for idx in range(len(df)):
        shift_id = int(df.iloc[idx]["_shift_id"])
        # MIX変更
        old_mix = df.iloc[idx]["MIX"]
        new_mix = edited_df.iloc[idx]["MIX"]
        if old_mix != new_mix:
            db.set_shift_mix(shift_id, int(new_mix))
            st.rerun()
        # 備考変更
        old_note = df.iloc[idx]["備考"] or ""
        new_note = edited_df.iloc[idx]["備考"] or ""
        if old_note != new_note:
            db.get_client().table("p1_shifts").update({"notes": new_note}).eq("id", shift_id).execute()
            st.rerun()
