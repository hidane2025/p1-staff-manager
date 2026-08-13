"""P1 Staff Manager — 出退勤管理（例外ベース）

原則：シフト通り＝デフォルト。例外だけ記録する。
- 「全員出勤」→ 来てない人だけ×
- 退勤は予定時刻で自動確定 → 延長/早退だけ修正
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.event_selector import select_event
from utils.time_input import MINUTE_CHOICES  # 分の刻みは1箇所で決める

st.set_page_config(page_title="出退勤", page_icon="🕐", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style, page_header, flow_bar
from utils.roles import CANONICAL_ROLES, DEPT_CHOICES, role_dept
from utils.calculator import parse_time_to_minutes
from dbx.shifts import _revert_payment_if_amount_affected
from utils.admin_guard import require_admin, admin_logout_button, current_role, operator_name
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="出退勤管理", roles=("admin", "viewer"),
              allow_day_code=True)

# 2026-08-12: 共催相手（韓国側）に進行状況だけ見せるため viewer を開放した。
# この画面は金額も本名も出さない（NO.・ディーラーネーム・役職・時刻のみ）が、
# 出退勤の記録そのものは書き換えられるので、viewer では更新操作を全て止める。
_READONLY = (current_role() == "viewer")
if _READONLY:
    st.info("👀 **閲覧のみのアカウントです。** 記録の変更はできません。")
admin_logout_button()

page_header("🕐 出退勤管理", "シフト通り＝デフォルト。例外（欠勤・遅刻/早入り・延長・早退）だけ記録します。")
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

# 部門フィルタ（ディーラー系=TAKAさん管理／受付系=豊浦さん・伊藤さん管理）。
# 一括操作・例外記録・一覧のすべてがこの絞り込みの対象になる
# （「全員出勤」を押しても、選んでいない部門には影響しない）。
_dept = st.radio("部門", list(DEPT_CHOICES), horizontal=True, key="attend_dept")
if _dept != "全員":
    shifts = [s for s in shifts if role_dept(s.get("role")) == _dept]
    if not shifts:
        st.info(f"{selected_date} の{_dept}のシフトはありません。")
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
# 2026-08-02: 実行環境のタイムゾーンに依存しないよう日本時間を明示する。
# （コンテナのTZ設定に加えた二重の防御。片方が外れても日付がずれない）
_JST = timezone(timedelta(hours=9))
today_str = datetime.now(_JST).strftime("%Y-%m-%d")
is_today = (selected_date == today_str)
now_str = datetime.now(_JST).strftime("%H:%M")

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
    if st.button(btn_label, type="primary", use_container_width=True,
                 disabled=_READONLY):
        if eligible_count == 0:
            st.info("対象のスタッフがいません（全員出勤済みまたは欠勤）")
        else:
            # A-7: 1件ずつ try/except。会場wifi断などでループ途中に切れても
            # 成功分は確定し、失敗分だけ再ボタンで再実行できる（成功者は対象外になる）。
            client = db.get_client()
            ok_n, fails = 0, []
            for s in eligible_shifts:
                try:
                    client.table("p1_shifts").update({
                        "actual_start": s["planned_start"],
                        "status": "checked_in",
                    }).eq("id", s["id"]).execute()
                    ok_n += 1
                except Exception:
                    fails.append(str(s.get("no") or s.get("staff_id") or s["id"]))
            if not fails:
                st.success(f"{ok_n}名を出勤にしました（予定開始が {now_str} 以前）")
                st.rerun()  # 全件成功時のみ再描画（失敗時は警告を残すため rerun しない）
            else:
                st.warning(
                    f"⚠️ {ok_n}名は出勤確定、{len(fails)}名は失敗（NO./ID: {', '.join(fails)}）。"
                    "通信状況を確認し、もう一度このボタンを押すと**失敗分だけ**再実行されます。"
                )

with col_bulk2:
    if st.button("🔴 全員退勤（予定時刻で確定）", use_container_width=True,
                 disabled=_READONLY):
        # A-7: 1件ずつ try/except。退勤は冪等なので失敗分は再ボタンで安全に再実行可能。
        client = db.get_client()
        targets = [s for s in shifts if s["status"] in ("checked_in", "scheduled")]
        ok_n, fails = 0, []
        for s in targets:
            try:
                actual_end = s.get("actual_end") or s["planned_end"]
                client.table("p1_shifts").update({
                    "actual_end": actual_end,
                    "actual_start": s.get("actual_start") or s["planned_start"],
                    "status": "checked_out",
                }).eq("id", s["id"]).execute()
                ok_n += 1
            except Exception:
                fails.append(str(s.get("no") or s["id"]))
        if not fails:
            st.success(f"{ok_n}名を予定時刻で退勤確定しました")
            st.rerun()  # 全件成功時のみ再描画（失敗時は警告を残す）
        else:
            st.warning(
                f"⚠️ {ok_n}名は退勤確定、{len(fails)}名は失敗（NO./ID: {', '.join(fails)}）。"
                "もう一度このボタンを押すと失敗分だけ再実行されます。"
            )

with col_bulk3:
    # 全体リセット（このボタンは「全員」が対象。1人だけ取り消したいときは
    # ② 例外を記録 → ↩️ 個別リセット を使用してください）
    if "confirm_reset" not in st.session_state:
        st.session_state["confirm_reset"] = False
    if not st.session_state["confirm_reset"]:
        if st.button("🔄 全員リセット", use_container_width=True,
                      help="この日の全員の出退勤記録を未確定に戻します。1人だけ取り消したいときは下の『↩️ 個別リセット』タブを使ってください。",
                      disabled=_READONLY):
            st.session_state["confirm_reset"] = True
            st.rerun()
    else:
        st.error("⚠️ この日の全員の出退勤データが未確定に戻ります")
        col_yes, col_no = st.columns(2)
        if col_yes.button("はい、全員リセットする", type="primary"):
            # A-7: 1件ずつ try/except。リセットは冪等なので失敗分は再実行で収束。
            client = db.get_client()
            ok_n, fails = 0, []
            for s in shifts:
                try:
                    client.table("p1_shifts").update({
                        "actual_start": None,
                        "actual_end": None,
                        "status": "scheduled",
                    }).eq("id", s["id"]).execute()
                    ok_n += 1
                except Exception:
                    fails.append(str(s.get("no") or s["id"]))
            st.session_state["confirm_reset"] = False
            if not fails:
                st.success(f"全員（{ok_n}名）のステータスをリセットしました")
                st.rerun()  # 全件成功時のみ再描画（失敗時は警告を残す）
            else:
                st.warning(
                    f"⚠️ {ok_n}名はリセット、{len(fails)}名は失敗（NO./ID: {', '.join(fails)}）。"
                    "もう一度実行すると失敗分だけ再処理されます。"
                )
        if col_no.button("キャンセル"):
            st.session_state["confirm_reset"] = False
            st.rerun()

# ============================================================
# セクション2: 例外だけ記録
# ============================================================
st.divider()
st.subheader("② 例外を記録（来てない人・時間が違う人だけ）")

# タブで操作を分ける（凍結退勤を最初＝最終日の主要操作）
tab_freeze, tab_absent, tab_late, tab_overtime, tab_early, tab_reset = st.tabs([
    "🧊 凍結退勤（一括）", "❌ 欠勤", "⏰ 遅刻・早入り", "⏩ 延長（残業）", "⏪ 早退", "↩️ 個別リセット"
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
    if st.button("❌ 選択した人を欠勤にする", key="mark_absent", disabled=_READONLY):
        if absent_staff:
            # A-7: 1件ずつ try/except。失敗分だけ再実行できる（冪等）。
            ok_n, fails = 0, []
            for name in absent_staff:
                s = staff_options[name]
                try:
                    db.mark_absent(s["id"])
                    ok_n += 1
                except Exception:
                    fails.append(str(s.get("no") or s["id"]))
            if not fails:
                st.success(f"{ok_n}名を欠勤にしました")
                st.rerun()  # 全件成功時のみ再描画（失敗時は警告を残す）
            else:
                st.warning(
                    f"⚠️ {ok_n}名を欠勤に、{len(fails)}名は失敗（NO./ID: {', '.join(fails)}）。"
                    "もう一度実行すると失敗分だけ再処理されます。"
                )

with tab_late:
    st.markdown("**実際の到着時刻**を記録します（遅刻・早入りの両方）。"
                "予定より**早い時刻**を入れれば早入りとして、その分も支払いに反映されます。")
    late_staff = st.selectbox("スタッフ", list(staff_options.keys()), key="late_select")
    if late_staff:
        s = staff_options[late_staff]
        st.info(f"予定出勤: {s['planned_start']}")
        col_lh, col_lm = st.columns(2)
        with col_lh:
            late_hour = st.number_input("時", min_value=0, max_value=30, value=min(int(s['planned_start'].split(':')[0]), 30), key="late_hour")
        with col_lm:
            late_min = st.selectbox("分", MINUTE_CHOICES, key="late_min")
        if st.button("⏰ この到着時刻で記録", key="mark_late", disabled=_READONLY):
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
        ot_hour = st.number_input("実際の退勤（時）", min_value=0, max_value=30, value=min(int(s['planned_end'].split(':')[0]) + 1, 30), key="ot_hour")
        ot_min = st.selectbox("実際の退勤（分）", MINUTE_CHOICES, key="ot_min")
        if st.button("⏩ 延長を記録", key="mark_ot", disabled=_READONLY):
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
            early_hour = st.number_input("時", min_value=0, max_value=30, value=min(max(0, int(s['planned_end'].split(':')[0]) - 1), 30), key="early_hour")
        with col_em:
            early_min = st.selectbox("分", MINUTE_CHOICES, key="early_min")
        if st.button("⏪ 早退を記録", key="mark_early", disabled=_READONLY):
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
            freeze_hour = st.number_input("退勤時刻（時）", min_value=0, max_value=30, value=int(datetime.now(_JST).strftime("%H")), key="freeze_hour")
        with col_fm:
            freeze_min = st.selectbox("退勤時刻（分）", MINUTE_CHOICES, key="freeze_min")
        if st.button("🧊 凍結退勤を実行", key="exec_freeze", type="primary", disabled=_READONLY):
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

with tab_reset:
    st.markdown(
        "**入力ミスや誤操作の取り消しに使います。** "
        "選んだ1名だけ、出勤・退勤・欠勤の記録を取り消して **未確定（予定通り）** に戻します。"
    )
    # 例外マーク（実時刻記録 or 欠勤）がついているスタッフだけ抽出
    has_exception = [
        s for s in shifts
        if s.get("actual_start") or s.get("actual_end") or s["status"] == "absent"
    ]
    if not has_exception:
        st.info("取り消せる例外記録がついているスタッフはまだいません。")
    else:
        # 表示ラベル: NO. 名前 (役職) — 状態：実時刻
        STATUS_LABEL = {
            "scheduled": "未確定",
            "checked_in": "出勤中",
            "checked_out": "退勤済",
            "absent": "欠勤",
        }
        reset_options = {}
        for s in has_exception:
            actual = ""
            if s.get("actual_start") or s.get("actual_end"):
                actual = f" [{s.get('actual_start', '—')}〜{s.get('actual_end', '—')}]"
            label = (
                f"NO.{s['no']} {s['name_jp']} ({s['role']}) — "
                f"{STATUS_LABEL.get(s['status'], s['status'])}{actual}"
            )
            reset_options[label] = s

        reset_target_label = st.selectbox(
            "リセットするスタッフ",
            list(reset_options.keys()),
            key="reset_target_select",
        )
        if reset_target_label:
            target = reset_options[reset_target_label]
            st.warning(
                f"**{target['name_jp']}** の出退勤記録を取り消します。"
                "既に支払い計算が行われている場合、その支払いを **未承認** に戻して再計算を促します。"
                "（支払済みの場合は保護されます）"
            )
            if st.button(
                "↩️ この人だけリセット",
                type="primary",
                key="exec_reset_individual",
                disabled=_READONLY,
            ):
                client = db.get_client()
                # シフト記録を未確定に戻す
                client.table("p1_shifts").update({
                    "actual_start": None,
                    "actual_end": None,
                    "status": "scheduled",
                }).eq("id", target["id"]).execute()
                # 影響する支払いを未承認に戻す（支払済みは保護される）
                payment_reset = db.reset_payment_to_pending(
                    event_id, target["staff_id"],
                    reason="個別リセット（出退勤）",
                )
                # 監査ログ
                try:
                    db.log_action(
                        "reset_attendance_individual", "shifts", target["id"],
                        detail=f"{target['name_jp']} (NO.{target['no']}) {selected_date}",
                        event_id=event_id,
                    )
                except Exception:
                    pass
                st.success(f"✅ {target['name_jp']} の出退勤記録をリセットしました")
                if payment_reset:
                    st.info(
                        "💡 該当の支払いを未承認に戻しました。"
                        "「💰 支払い計算」ページで再計算してください。"
                    )
                st.rerun()

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
        new_role = st.selectbox("役職", list(CANONICAL_ROLES) + ["Other"], key="new_staff_role")
    add_staff_data = None

col_sh, col_sm, col_eh2, col_em2 = st.columns(4)
with col_sh:
    add_start_hour = st.number_input("開始（時）", min_value=0, max_value=30, value=18, key="add_start_h")
with col_sm:
    add_start_min = st.selectbox("開始（分）", MINUTE_CHOICES, key="add_start_m")
with col_eh2:
    add_end_hour = st.number_input("終了（時）", min_value=0, max_value=30, value=23, key="add_end_h")
with col_em2:
    add_end_min = st.selectbox("終了（分）", MINUTE_CHOICES, key="add_end_m")

if st.button("➕ 当日シフトに追加", key="exec_add_staff", type="primary",
             disabled=_READONLY):
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

# 直近の編集で弾いた理由を、再描画後も見えるように表示（st.warning+rerunだと消える）
if st.session_state.get("_att_flash"):
    st.warning(st.session_state.pop("_att_flash"))

# 実到着・実退勤のプルダウン選択肢（5分刻み・「—」=未記録/取り消し）
_TIME_OPTS = ["—"] + [f"{h:02d}:{m:02d}" for h in range(7, 30) for m in range(0, 60, 5)] + ["30:00"]

# 並び順はサーバー側で固定する。表ヘッダのクリック並び替えはブラウザ側の
# 一時状態のため、時刻を保存するたびの再描画で消えてしまう（2026-08-14 指摘）。
# 選んだ並び順は別ページへ移動しても残す（widgetのstateはページ切替で消えるため別キーに写す）
_SORT_OPTS = ["NO.順", "予定時刻順", "未確定を上に"]
_sort_default = st.session_state.get("_att_sort_persist", "NO.順")
_col_sort, _col_re = st.columns([4, 1])
with _col_sort:
    _sort = st.radio(
        "並び順", _SORT_OPTS, horizontal=True,
        index=_SORT_OPTS.index(_sort_default) if _sort_default in _SORT_OPTS else 0,
        key="att_sort")
st.session_state["_att_sort_persist"] = _sort
with _col_re:
    # 2026-08-13 中野さん指示「ボタン押したら並び替え変わるのやめて」:
    # 行の順序は一度決めたら固定し、チェックや時刻入力で行が飛ばないようにする。
    # 最新の状態で並べ直したい時だけこのボタンを押す。
    if st.button("🔄 並び直す", disabled=_READONLY,
                 help="現在の出退勤状況で並びを作り直します（普段は行が動かないよう固定）"):
        st.session_state.pop("_att_order_sig", None)
        st.rerun()

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
    elif s.get("actual_start") and s.get("planned_start") and s["actual_start"] < s["planned_start"]:
        # 予定より早い到着は「早入り」。以前は遅刻の裏返しで無表示だったため、
        # 早く来た事実（＝支払い増の根拠）が一覧から見えなかった
        note = f"🌅 早入り（{s['actual_start']}着）"
    elif s.get("actual_end") and s.get("planned_end") and s["actual_end"] > s["planned_end"]:
        note = f"⏩ 延長（{s['actual_end']}退勤）"
    elif s.get("actual_end") and s.get("planned_end") and s["actual_end"] < s["planned_end"]:
        note = f"⏪ 早退（{s['actual_end']}退勤）"

    display.append({
        "NO.": s["no"],
        "名前": s["name_jp"],
        "役職": s["role"],
        "予定": planned,
        "出勤": s["status"] in ("checked_in", "checked_out"),
        "退勤": s["status"] == "checked_out",
        "実到着": actual_start,
        "実退勤": actual_end,
        "状態": STATUS_DISPLAY.get(s["status"], s["status"]),
        "例外": note,
        "MIX": bool(s.get("is_mix", 0)),
        "備考": s.get("notes") or "",
        "_shift_id": s["id"],
    })

def _sort_key_planned(row):
    m = parse_time_to_minutes((row["予定"] or "").split("〜")[0])
    return (m if m is not None else 9999, row["NO."] or 9999)


def _apply_sort(rows):
    rows = list(rows)
    if _sort == "予定時刻順":
        rows.sort(key=_sort_key_planned)
    elif _sort == "未確定を上に":
        _order = {"⬜ 未確定": 0, "🟢 出勤中": 1, "✅ 退勤済": 2, "❌ 欠勤": 3}
        rows.sort(key=lambda r: (_order.get(r["状態"], 9), _sort_key_planned(r)))
    else:
        rows.sort(key=lambda r: (r["NO."] or 9999))
    return rows


# 行順の固定（2026-08-13）: チェックや時刻保存のたびに行が飛ぶと押し間違いの元。
# 並び順・日付・部門を変えた時と「🔄 並び直す」の時だけ順序を作り直し、
# それ以外は最初に決めた順序を維持する（途中で状態が変わっても行は動かない）。
_order_sig = (f"{event_id}|{selected_date}|{_sort}|"
              f"{st.session_state.get('attend_dept', '全員')}")
if (st.session_state.get("_att_order_sig") != _order_sig
        or not st.session_state.get("_att_order")):
    display = _apply_sort(display)
    st.session_state["_att_order"] = [r["_shift_id"] for r in display]
    st.session_state["_att_order_sig"] = _order_sig
else:
    _pos = {sid: i for i, sid in enumerate(st.session_state["_att_order"])}
    # 固定後に追加された行（当日シフト追加）は末尾へ
    display.sort(key=lambda r: (_pos.get(r["_shift_id"], 10 ** 9), r["NO."] or 9999))

df = pd.DataFrame(display)

# 出勤・MIX・備考を編集可能にしたテーブル
edited_df = st.data_editor(
    df,
    use_container_width=True,
    hide_index=True,
    height=600,
    # 2026-08-14 中野さん指示「一覧に直接記入する運用が一番」:
    # 実到着・実退勤を直接編集可能にする。viewer（閲覧用）は表ごと編集不可
    disabled=True if _READONLY else
    ["NO.", "名前", "役職", "予定", "状態", "例外", "_shift_id"],
    column_config={
        "出勤": st.column_config.CheckboxColumn(
            "✅出勤", default=False,
            help="チェック＝予定時刻どおり出勤として確定。外す＝未確定に戻す。",
        ),
        "退勤": st.column_config.CheckboxColumn(
            "🔴退勤", default=False,
            help="チェック＝予定時刻どおり退勤として確定（未出勤なら出勤も予定時刻で記録）。"
                 "外す＝出勤中に戻す。時刻がズレた時は実退勤のプルダウンで。",
        ),
        "実到着": st.column_config.SelectboxColumn(
            "実到着", options=_TIME_OPTS,
            help="プルダウンから選択（文字を打つと絞り込み）。「—」で取り消し"),
        "実退勤": st.column_config.SelectboxColumn(
            "実退勤", options=_TIME_OPTS,
            help="プルダウンから選択。深夜は 25:30 等の24時超表記。「—」で取り消し"),
        "MIX": st.column_config.CheckboxColumn("MIX", default=False),
        "備考": st.column_config.TextColumn("備考", help="イレギュラー対応等を自由入力"),
        "_shift_id": None,
    },
    key="shift_table",
)

# 変更検出・保存（出勤・実到着・実退勤・MIX・備考）。viewerは適用しない
_shift_by_id = {s["id"]: s for s in shifts}
_paid_staff = {p["staff_id"] for p in (db.get_payments_for_event(event_id) or [])
               if p.get("status") == "paid"}


def _norm_edit_time(v):
    """一覧に打ち込まれた時刻を正規化。(値 or None, 妥当か) を返す"""
    v = str(v or "").strip()
    if v in ("", "—", "-", "ー", "None"):
        return None, True
    m = parse_time_to_minutes(v)
    if m is None or not (0 <= m < 48 * 60):
        return None, False
    return f"{m // 60:02d}:{m % 60:02d}", True


def _flash_and_rerun(msg):
    """警告を再描画後も残す（st.warning+rerunだと消えるため session_state 経由）"""
    st.session_state["_att_flash"] = msg
    st.rerun()


if (not _READONLY) and not df.empty and not edited_df.empty:
    for idx in range(len(df)):
        shift_id = int(df.iloc[idx]["_shift_id"])
        # 実到着・実退勤の直接編集（リスト記入運用が正・2026-08-14）
        for _col in ("実到着", "実退勤"):
            _old_v = str(df.iloc[idx][_col]).strip()
            _new_v = str(edited_df.iloc[idx][_col]).strip()
            if _old_v == _new_v:
                continue
            srow = _shift_by_id.get(shift_id, {})
            def _flash(msg):
                st.session_state["_att_flash"] = msg
                st.rerun()

            if srow.get("status") == "absent":
                _flash("⚠️ 欠勤の人は「②例外を記録→個別リセット」で戻してから入力してください。")
            if srow.get("staff_id") in _paid_staff:
                _flash(f"⚠️ {srow.get('name_jp', '')} は支払い済みのため時刻を変更できません。")
            _nt, _ok = _norm_edit_time(_new_v)
            if not _ok:
                _flash(f"⚠️ 時刻を読めません:「{_new_v}」")
            _ns = _nt if _col == "実到着" else _norm_edit_time(df.iloc[idx]["実到着"])[0]
            _ne = _nt if _col == "実退勤" else _norm_edit_time(df.iloc[idx]["実退勤"])[0]
            if _ne and not _ns:
                _flash(f"⚠️ {srow.get('name_jp', '')}: 退勤だけは記録できません。先に実到着を選んでください。")
            if _ns and _ne and parse_time_to_minutes(_ne) < parse_time_to_minutes(_ns):
                _flash(f"⚠️ {srow.get('name_jp', '')}: 退勤が到着より前です。深夜は 25:30 のような24時超表記で。")
            _new_status = ("checked_out" if _ne else
                           "checked_in" if _ns else "scheduled")
            db.get_client().table("p1_shifts").update({
                "actual_start": _ns, "actual_end": _ne, "status": _new_status,
            }).eq("id", shift_id).execute()
            # 実績が変わったら計算済みの支払いを未承認へ（支払済みは上で弾いている）
            _revert_payment_if_amount_affected(
                srow, reason=f"一覧で実績を編集 {_ns or '—'}〜{_ne or '—'}（要再計算）")
            db.log_action(
                "attendance_edit", "shifts", shift_id,
                detail=(f"{srow.get('name_jp', '')} (NO.{srow.get('no', '—')}) "
                        f"{selected_date} 一覧編集 {_col}: "
                        f"{_old_v or '—'} → {_nt or '—'}"),
                event_id=event_id, performed_by=operator_name())
            st.rerun()
        # 退勤チェック変更（🔴=予定時刻で退勤確定 / 解除=出勤中に戻す）2026-08-13 中野さん要望
        old_out = bool(df.iloc[idx]["退勤"])
        new_out = bool(edited_df.iloc[idx]["退勤"])
        if old_out != new_out:
            srow = _shift_by_id.get(shift_id, {})
            status = srow.get("status")
            if srow.get("staff_id") in _paid_staff:
                _flash_and_rerun(f"⚠️ {srow.get('name_jp', '')} は支払い済みのため変更できません。")
            if status == "absent":
                _flash_and_rerun("⚠️ 欠勤の人は「②例外を記録→個別リセット」で戻してから操作してください。")
            if new_out:
                # 未出勤なら出勤も予定時刻で記録してから退勤（退勤だけの記録を作らない）
                if status == "scheduled":
                    db.checkin_staff(shift_id, srow.get("planned_start"))
                db.checkout_staff(shift_id, srow.get("planned_end"))
                db.log_action(
                    "attendance_edit", "shifts", shift_id,
                    detail=(f"{srow.get('name_jp', '')} (NO.{srow.get('no', '—')}) "
                            f"{selected_date} 退勤チェック＝予定時刻 "
                            f"{srow.get('planned_end')} で退勤確定"),
                    event_id=event_id, performed_by=operator_name())
            else:
                db.get_client().table("p1_shifts").update({
                    "actual_end": None, "status": "checked_in",
                }).eq("id", shift_id).execute()
                _revert_payment_if_amount_affected(
                    srow, reason="退勤チェック解除（出勤中に戻す・要再計算）")
                db.log_action(
                    "attendance_edit", "shifts", shift_id,
                    detail=(f"{srow.get('name_jp', '')} (NO.{srow.get('no', '—')}) "
                            f"{selected_date} 退勤チェック解除→出勤中に戻す"),
                    event_id=event_id, performed_by=operator_name())
            st.rerun()
        # 出勤チェック変更（✅=予定時刻で出勤確定 / 解除=未確定に戻す）
        old_att = bool(df.iloc[idx]["出勤"])
        new_att = bool(edited_df.iloc[idx]["出勤"])
        if old_att != new_att:
            srow = _shift_by_id.get(shift_id, {})
            status = srow.get("status")
            if new_att and status == "scheduled":
                db.checkin_staff(shift_id, srow.get("planned_start"))
            elif (not new_att) and status == "checked_in" and not srow.get("actual_end"):
                db.get_client().table("p1_shifts").update({
                    "actual_start": None, "status": "scheduled",
                }).eq("id", shift_id).execute()
            else:
                # 退勤済・欠勤などはここでは変更させない（再描画で表示が元に戻る）
                st.warning("退勤済・欠勤の変更は「②例外を記録」の個別リセットから行ってください。")
            st.rerun()
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
