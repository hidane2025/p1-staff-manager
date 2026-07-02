"""P1 Staff Manager — ピット端末（v3.8 現場フィードバック対応）

【役割】
ピット側オペレーター用の専用画面。最終勤怠後、ディーラーが給与受け取りに来る前に
**退勤打刻と支払い計算を即時更新** する。

【業務フロー】
1. ディーラーが退勤を申告（口頭）
2. ピット担当が NO. を入力 → 当日の勤怠＋現時点での試算支払額を確認
3. 退勤時刻を入力 → 「✅ 退勤＋支払い確定」を押す
4. システム: shift.actual_end / status=checked_out / 支払い記録を pending で保存
5. ディーラーは給与支払いの窓口で「確認だけ」して受け取る

【設計上の判断】
- 個人情報（本名・住所等）は表示しない（ピット側にスタッフの本名は不要）
- 支払額・勤怠は表示する（ピット運用の核）
- 給与支払い側（91_領収書発行 など）は require_admin で従来通り保護
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import db
from utils.calculator import calculate_staff_payment, parse_shift_time
from utils.event_selector import select_event
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import (
    apply_global_style, page_header, flow_bar, section_header, kpi_row,
)
from utils.admin_guard import (
    require_admin, admin_logout_button, operator_name, is_auth_enabled,
)


def _operator_attributable() -> bool:
    """承認を実オペレーターに帰属できるか。

    パスワードレス運用（ADMIN_PASSWORD 未設定）ではログイン導線が無いため常に True。
    認証有効時はオペレーター名が匿名/空白でないことを要求する（pages/3 と同基準）。
    自動承認は支払いを「承認済み」に確定させる内部統制操作なので、ここでも帰属を必須化。
    """
    if not is_auth_enabled():
        return True
    return (operator_name() or "").strip() not in {"", "anonymous", "anonymous_admin"}


_JST = timezone(timedelta(hours=9))


st.set_page_config(page_title="ピット端末", page_icon="🎰", layout="wide")
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="ピット端末")
admin_logout_button()

page_header(
    "🎰 ピット端末",
    "退勤打刻と支払い計算を一画面で。NO. を入れて時刻を確定すれば、給与支払い側は「確認だけ」になります。",
)
flow_bar(active="calc", done=["setup", "input"])

# UX B (2026-05-09): 直前の確定結果を大きく表示（次のスタッフ受付の前に視覚的に確認）
_LAST_CONFIRMED_KEY = "_pit_last_confirmed"
if st.session_state.get(_LAST_CONFIRMED_KEY):
    _last = st.session_state[_LAST_CONFIRMED_KEY]
    st.markdown(
        f'<div class="p1-pit-confirmed">'
        f'<div class="p1-pit-confirmed-title">直前の確定（次の人を呼ぶ前にここを確認）</div>'
        f'<div class="p1-pit-confirmed-amount">¥{_last["amount"]:,}</div>'
        f'<div class="p1-pit-confirmed-name">'
        f'NO.{_last["no"]} {_last["name"]}　'
        f'退勤 {_last["checkout"]}　'
        f'{"🟡 承認済" if _last.get("approved") else "⏳ 未承認"}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if st.button("✅ 確認した（次のスタッフへ）", use_container_width=True):
        st.session_state.pop(_LAST_CONFIRMED_KEY, None)
        st.rerun()

# A-11: 退勤は確定したが支払い計算が失敗したケースを、リラン後も画面上部に
# 残して次のスタッフを呼ぶ前に必ず気づけるようにする（st.rerun は描画を破棄する
# ため、警告は session_state に退避してここで再表示する）。
_PIT_ERROR_KEY = "_pit_payment_error"
if st.session_state.get(_PIT_ERROR_KEY):
    _err = st.session_state[_PIT_ERROR_KEY]
    st.warning(
        f"⚠️ **{_err.get('name', '対象スタッフ')}** の**シフトは退勤確定済み**ですが、"
        "支払い計算/保存でエラーが発生しました。"
        "「💰 支払い計算」ページで該当スタッフを再計算してください。"
        "（退勤打刻は失われていません）"
    )
    if _err.get("detail"):
        with st.expander("🔧 技術詳細（管理者向け）"):
            st.code(_err["detail"], language=None)
    if st.button("了解（この警告を閉じる）", key="dismiss_pit_error"):
        st.session_state.pop(_PIT_ERROR_KEY, None)
        st.rerun()


# ============================================================
# 1. イベント選択
# ============================================================
events = db.get_all_events()
if not events:
    st.warning("⚠️ イベントが未作成です。先に「📋 イベント設定」で作成してください。")
    st.stop()

event_id = select_event(events, "対象イベント")
event = db.get_event_by_id(event_id) or {}

st.markdown(
    f"📍 **{event.get('name', '—')}** "
    f"（{event.get('start_date', '—')} 〜 {event.get('end_date', '—')}）"
)

# ============================================================
# 1.5 配布チェック：弁当①・弁当②（12h+）・ドリンク券（2026-06-18 / 2026-07-02 拡張）
# ============================================================
# シフトある人を一覧で出し、配布／辞退／未受領を1タップで切替。
# 弁当は基本1個、予定シフト12時間以上の人だけ「2個目」ボタンが出る。
# ドリンクチケットは一律2枚＝「配布」トグル1つ。
# マイグレ未実行のDBでは「マイグレ案内」を出して機能を無効化。
_rates_for_lunch = db.get_event_rates(event_id) or []
_lunch_dates = [r["date"] for r in _rates_for_lunch] or [event.get("start_date")]

with st.expander("📦 配布チェック：弁当・ドリンク券（当日の出勤予定者）", expanded=False):
    _lunch_date = st.selectbox(
        "対象日", _lunch_dates,
        key="lunch_date_select",
        help="出勤予定者の一覧を表示します。欠勤者は対象外。",
    )

    _summary = db.get_handout_summary(event_id, _lunch_date)
    _total = _summary["total_active"]
    _lu = _summary["lunch"]
    _migrated = _summary["migrated"]

    if _total == 0:
        st.info("この日の出勤予定者がいません（シフト未取込か全員欠勤）。")
    else:
        # 個別行データを先に取得（弁当2個目の対象者数を数えるため）
        _shifts_today = [
            s for s in (db.get_shifts_for_event(event_id, date=_lunch_date) or [])
            if (s.get("status") or "") != "absent"
        ]
        _shifts_today.sort(key=lambda s: (s.get("no") or 9999))
        _lunch2_targets = [
            s for s in _shifts_today
            if db.planned_shift_minutes(s.get("planned_start"), s.get("planned_end"))
            >= db.LUNCH2_THRESHOLD_MINUTES
        ]
        _lunch2_ids = {s["id"] for s in _lunch2_targets}

        _bar = (_lu["received"] + _lu["cancelled"]) / _total if _total else 0
        st.progress(_bar, text=(
            f"🍱 弁当: {_lu['received'] + _lu['cancelled']}/{_total}人"
            f"（受領 {_lu['received']} / 辞退 {_lu['cancelled']} / 未受領 {_lu['pending']}）"
        ))
        if _migrated:
            _l2 = _summary["lunch2"]
            _dr = _summary["drink"]
            # 2個目サマリは「対象者のうち何人に渡したか」で表示
            _l2_recv_in_targets = sum(
                1 for s in _lunch2_targets
                if (s.get("lunch2_status") or "pending").lower() == "received"
            )
            _dr_done = _dr["received"] + _dr["cancelled"]
            st.progress(
                (_l2_recv_in_targets / len(_lunch2_targets)) if _lunch2_targets else 0.0,
                text=f"🍱🍱 弁当2個目（12h以上 {len(_lunch2_targets)}名対象）: 配布済 {_l2_recv_in_targets}/{len(_lunch2_targets)}人",
            )
            st.progress(
                (_dr_done / _total) if _total else 0.0,
                text=f"🎫 ドリンク券（一律2枚）: {_dr_done}/{_total}人（配布済 {_dr['received']} / 辞退 {_dr['cancelled']}）",
            )
            st.caption(f"📊 本日の必要数目安 — 弁当 {_total - _lu['cancelled'] + len(_lunch2_targets)}個 / ドリンク券 {(_total - _dr['cancelled']) * 2}枚")

        c_all1, c_all2, c_all3, c_all4 = st.columns(4)
        with c_all1:
            if st.button("✅ 弁当 全員受領", use_container_width=True, key="lunch_bulk_received"):
                if not _operator_attributable():
                    st.warning("オペレーター名を上で入力してから操作してください。")
                else:
                    n = db.bulk_set_lunch_status(event_id, _lunch_date, "received",
                                                  performed_by=operator_name())
                    st.success(f"{n}名を受領済みにしました。")
                    st.rerun()
        with c_all2:
            if st.button("🔄 弁当 全員戻す", use_container_width=True, key="lunch_bulk_pending"):
                if not _operator_attributable():
                    st.warning("オペレーター名を上で入力してから操作してください。")
                else:
                    n = db.bulk_set_lunch_status(event_id, _lunch_date, "pending",
                                                  performed_by=operator_name())
                    st.success(f"{n}名を未受領に戻しました。")
                    st.rerun()
        with c_all3:
            if st.button("🎫 ドリンク 全員配布", use_container_width=True, key="drink_bulk_received",
                          disabled=not _migrated):
                if not _operator_attributable():
                    st.warning("オペレーター名を上で入力してから操作してください。")
                else:
                    n = db.bulk_set_distribution_status(event_id, _lunch_date, "drink", "received",
                                                         performed_by=operator_name())
                    st.success(f"{n}名をドリンク配布済みにしました。")
                    st.rerun()
        with c_all4:
            if st.button("🔄 ドリンク 全員戻す", use_container_width=True, key="drink_bulk_pending",
                          disabled=not _migrated):
                if not _operator_attributable():
                    st.warning("オペレーター名を上で入力してから操作してください。")
                else:
                    n = db.bulk_set_distribution_status(event_id, _lunch_date, "drink", "pending",
                                                         performed_by=operator_name())
                    st.success(f"{n}名を未配布に戻しました。")
                    st.rerun()

        st.divider()

        # 個別行（出勤予定者を NO. 順で）
        # 列: 名前 | 弁当:受領/辞退/戻す | 弁当2個目(対象者のみ) | ドリンク券
        for s in _shifts_today:
            _ls = (s.get("lunch_status") or "pending").lower()
            _l2s = (s.get("lunch2_status") or "pending").lower()
            _drs = (s.get("drink_status") or "pending").lower()
            _icon = {"received": "✅", "cancelled": "🚫", "pending": "⬜"}.get(_ls, "⬜")
            _is_l2 = s["id"] in _lunch2_ids
            cols = st.columns([2.4, 0.9, 0.9, 0.9, 1.2, 1.2])
            with cols[0]:
                _mins = db.planned_shift_minutes(s.get("planned_start"), s.get("planned_end"))
                _l2_badge = (
                    f"<span style='background:#FEF3C7;color:#92400E;font-size:10px;"
                    f"padding:1px 6px;border-radius:8px;margin-left:6px;'>12h+（{_mins // 60}h）</span>"
                    if _is_l2 else ""
                )
                st.markdown(
                    f"**{_icon} NO.{s.get('no', '—')} {s.get('name_jp', '—')}**"
                    f"<span style='color:#94A3B8;font-size:11px;margin-left:8px;'>{s.get('role', '')}</span>"
                    f"{_l2_badge}",
                    unsafe_allow_html=True,
                )
            with cols[1]:
                if st.button("✅ 受領", key=f"lunch_recv_{s['id']}",
                              use_container_width=True,
                              disabled=(_ls == "received")):
                    if not _operator_attributable():
                        st.warning("オペレーター名を上で入力してから操作してください。")
                    else:
                        db.update_lunch_status(s["id"], "received",
                                                performed_by=operator_name())
                        st.rerun()
            with cols[2]:
                if st.button("🚫 辞退", key=f"lunch_cncl_{s['id']}",
                              use_container_width=True,
                              disabled=(_ls == "cancelled")):
                    if not _operator_attributable():
                        st.warning("オペレーター名を上で入力してから操作してください。")
                    else:
                        db.update_lunch_status(s["id"], "cancelled",
                                                performed_by=operator_name())
                        st.rerun()
            with cols[3]:
                if st.button("🔄 戻す", key=f"lunch_rst_{s['id']}",
                              use_container_width=True,
                              disabled=(_ls == "pending")):
                    if not _operator_attributable():
                        st.warning("オペレーター名を上で入力してから操作してください。")
                    else:
                        db.update_lunch_status(s["id"], "pending",
                                                performed_by=operator_name())
                        st.rerun()
            with cols[4]:
                if _is_l2:
                    _l2_label = "🍱② 済（戻す）" if _l2s == "received" else "🍱② 2個目"
                    if st.button(_l2_label, key=f"lunch2_{s['id']}",
                                  use_container_width=True,
                                  type=("secondary" if _l2s == "received" else "primary"),
                                  disabled=not _migrated):
                        if not _operator_attributable():
                            st.warning("オペレーター名を上で入力してから操作してください。")
                        else:
                            _new = "pending" if _l2s == "received" else "received"
                            if not db.update_distribution_status(
                                    s["id"], "lunch2", _new, performed_by=operator_name()):
                                st.warning("保存できません。DBマイグレ未適用の可能性があります。")
                            st.rerun()
                else:
                    st.caption("")  # 12h未満は2個目対象外
            with cols[5]:
                _dr_label = "🎫 済（戻す）" if _drs == "received" else "🎫 2枚配布"
                if st.button(_dr_label, key=f"drink_{s['id']}",
                              use_container_width=True,
                              type=("secondary" if _drs == "received" else "primary"),
                              disabled=not _migrated):
                    if not _operator_attributable():
                        st.warning("オペレーター名を上で入力してから操作してください。")
                    else:
                        _new = "pending" if _drs == "received" else "received"
                        if not db.update_distribution_status(
                                s["id"], "drink", _new, performed_by=operator_name()):
                            st.warning("保存できません。DBマイグレ未適用の可能性があります。")
                        st.rerun()

        if not _migrated:
            st.warning("⚠️ 弁当2個目・ドリンク券の列が未追加です。管理者に "
                       "`docs/db_migrations/20260702_add_lunch2_drink_status.sql` の適用を依頼してください"
                       "（適用まで🍱②・🎫ボタンは無効）。")
        st.caption("⚠️ 列 `lunch_status` が未追加の旧DBでは弁当ボタンが反応しません。"
                   "その場合は `docs/db_migrations/20260618_add_lunch_status.sql` の適用が必要です。")

# ============================================================
# 2. スタッフ検索（NO. または ディーラーネーム）
# ============================================================
section_header(
    "スタッフを検索",
    "NO. を入力して Enter または ディーラーネームの一部を入力。",
)

col_search1, col_search2 = st.columns([1, 2])
with col_search1:
    pit_no_input = st.text_input(
        "NO.（数字）",
        placeholder="例: 18",
        key="pit_no_input",
    )
with col_search2:
    pit_name_input = st.text_input(
        "ディーラーネーム",
        placeholder="例: EveKat（部分一致）",
        key="pit_name_input",
    )

# 候補を絞り込む
all_staff = db.get_all_staff()
candidates = []
if pit_no_input:
    try:
        no_val = int(pit_no_input.strip())
        candidates = [s for s in all_staff if s.get("no") == no_val]
    except ValueError:
        st.error("NO. は数字で入れてください")
elif pit_name_input:
    q = pit_name_input.strip().lower()
    candidates = [
        s for s in all_staff
        if q in (s.get("name_jp", "") or "").lower()
        or q in (s.get("name_en", "") or "").lower()
    ][:10]

if not candidates:
    if pit_no_input or pit_name_input:
        st.warning("該当するスタッフが見つかりません。")
    st.stop()

if len(candidates) == 1:
    target = candidates[0]
else:
    target_label = st.selectbox(
        "候補から選択",
        [
            f"NO.{s.get('no', '?')} {s.get('name_jp', '')} ({s.get('role', '')})"
            for s in candidates
        ],
    )
    target = candidates[
        [
            f"NO.{s.get('no', '?')} {s.get('name_jp', '')} ({s.get('role', '')})"
            for s in candidates
        ].index(target_label)
    ]


# ============================================================
# 3. 当日の勤怠を取得（イベント期間内すべて）
# ============================================================
all_event_shifts = db.get_shifts_for_event(event_id, staff_id=target["id"])
if not all_event_shifts:
    st.error(
        f"⚠️ {target['name_jp']} のシフトがこのイベントに登録されていません。"
        "「シフト取込」ページで取り込んでください。"
    )
    st.stop()

# Codex 4回目 P2 #9 + 5回目 P2 #12 + 6回目 P2 #13 fix (2026-05-09): 深夜跨ぎ対応
# 25:00 / 29:00 で終わるシフトの退勤打刻は 0:00 を超えてから来ることが多い。
# 優先順位を以下に統一:
#   1. checked_in 状態のシフト（出勤中＝必ずこの人を退勤させたい）
#   2. 「厳密に前日」かつ「深夜跨ぎ planned_end ≥ 24:00」の scheduled シフト
#      → 古い no-show（2日以上前の scheduled）を誤って優先しない
#   3. 当日の scheduled シフト
#   4. 最新のシフト（全部確定済みのケース）
_now_date = datetime.now(_JST).strftime("%Y-%m-%d")
_prev_date = (datetime.now(_JST).date() - timedelta(days=1)).strftime("%Y-%m-%d")


def _is_overnight_shift(s: dict) -> bool:
    """planned_end が 24:00 以降のシフト = 深夜跨ぎシフト判定"""
    end = (s.get("planned_end") or "").strip()
    try:
        h = int(end.split(":")[0])
        return h >= 24
    except (ValueError, IndexError):
        return False


# 1. checked_in 最優先
_checked_in = [s for s in all_event_shifts if s.get("status") == "checked_in"]

# 2. 「厳密に前日 + 深夜跨ぎ」の scheduled シフトのみ
_scheduled = [s for s in all_event_shifts if s.get("status") == "scheduled"]
_yesterday_overnight = [
    s for s in _scheduled
    if s.get("date") == _prev_date and _is_overnight_shift(s)
]
_today_scheduled = [s for s in _scheduled if s.get("date") == _now_date]

if _checked_in:
    # 出勤中があれば最も古い（深夜跨ぎなら前日）を優先
    _default_shift = sorted(_checked_in, key=lambda s: s.get("date", ""))[0]
elif _yesterday_overnight:
    # 未check-in＋前日深夜シフト → 深夜跨ぎ運用と推定
    _default_shift = _yesterday_overnight[0]
elif _today_scheduled:
    _default_shift = _today_scheduled[0]
else:
    # 全シフト確定済み or 古い no-show のみ → 現在日付 or 最新日のシフトを表示
    _default_shift = next(
        (s for s in all_event_shifts if s.get("date") == _now_date),
        all_event_shifts[-1],
    )

# 操作者が手動で別の日付を選べるように
_shift_dates = sorted({s["date"] for s in all_event_shifts})
_default_idx = (
    _shift_dates.index(_default_shift["date"])
    if _default_shift["date"] in _shift_dates else 0
)
selected_shift_date = st.selectbox(
    "シフト日付（深夜跨ぎ時はここで前日を選択）",
    _shift_dates,
    index=_default_idx,
    help="現在時刻が 0:00 を超えていても、前日のシフトを選び直せます。"
    "未確定/出勤中のシフトがある日が自動的に選ばれます。",
)
today = selected_shift_date  # 既存変数名を維持（互換性のため）
today_shift = next(
    (s for s in all_event_shifts if s.get("date") == today), None
)

# ============================================================
# UX B (2026-05-09): スタッフサマリーを「上段固定」風の大きいカードに
# ============================================================

EMPLOYMENT_LABELS = {
    "contractor": "業務委託",
    "timee": "タイミー",
    "fulltime": "正社員",
}
emp_label = EMPLOYMENT_LABELS.get(
    target.get("employment_type") or "contractor",
    target.get("employment_type") or "—",
)

custom_rate = target.get("custom_hourly_rate")
custom_rate_display = f"¥{custom_rate:,}" if custom_rate else "イベント基本時給"

# 当日シフト概要を1行で
_today_shift_quick = next(
    (s for s in all_event_shifts if s.get("date") == today), None
)
if _today_shift_quick:
    _quick_planned = (
        f"{_today_shift_quick.get('planned_start', '—')}〜{_today_shift_quick.get('planned_end', '—')}"
    )
    _quick_actual = (
        f"{_today_shift_quick.get('actual_start', '—')}〜{_today_shift_quick.get('actual_end', '—')}"
    )
    _quick_status = {
        "scheduled": "⬜ 未確定",
        "checked_in": "🟢 出勤中",
        "checked_out": "✅ 退勤済",
        "absent": "❌ 欠勤",
    }.get(_today_shift_quick.get("status", ""), _today_shift_quick.get("status", ""))
else:
    _quick_planned = "—"
    _quick_actual = "—"
    _quick_status = "—"

# 上段の固定スタッフカード
st.markdown(
    f'<div class="p1-pit-summary">'
    f'<div class="p1-pit-summary-name">'
    f'👤 NO.{target.get("no", "?")} {target["name_jp"]}　'
    f'<span style="font-size:14px; color:#475569; font-weight:500;">'
    f'({target.get("role", "—")} / {emp_label})</span>'
    f'</div>'
    f'<div class="p1-pit-summary-meta">'
    f'時給: <strong>{custom_rate_display}</strong>　／　'
    f'{today} 予定: <strong>{_quick_planned}</strong>　実績: {_quick_actual}　'
    f'<span style="margin-left:8px;">{_quick_status}</span>'
    f'</div>'
    f'</div>',
    unsafe_allow_html=True,
)

# Phase 3-I: 個別手当の状態を表示（オフレコ手当は内訳非表示）
indiv_allowances = db.get_individual_allowances(event_id, target["id"])
if indiv_allowances:
    open_count = sum(1 for a in indiv_allowances if not a.get("is_off_record"))
    off_count = sum(1 for a in indiv_allowances if a.get("is_off_record"))
    open_total = sum(int(a.get("amount") or 0) for a in indiv_allowances if not a.get("is_off_record"))
    msg_parts = []
    if open_count:
        msg_parts.append(f"通常 {open_count}件 (¥{open_total:,})")
    if off_count:
        msg_parts.append("オフレコ手当あり（金額は支給時画面で確認）")
    st.info("🎁 個別手当: " + " ／ ".join(msg_parts))


# ============================================================
# 5. 当日のシフト＋退勤打刻
# ============================================================
section_header(
    "当日の勤怠",
    f"今日の日付: {today}（JST）",
)

# ============================================================
# Phase 3-F: 交通費領収書をピット端末でも入力可能に
# ============================================================
with st.expander("🚃 交通費の領収書金額を入力（任意）", expanded=False):
    st.caption(
        "ディーラーから「電車代の領収書あります」と言われたら、ここで金額を入れて保存。"
        "イベントの地域別ルール（上限・領収書要否）に従って精算額が自動算出されます。"
        "後で給与窓口でも調整可能です。"
    )
    # 既存の請求があれば表示
    existing_claims = db.get_transport_claims(event_id) or []
    existing_for_t = next(
        (c for c in existing_claims if c.get("staff_id") == target["id"]), None
    )
    if existing_for_t:
        st.info(
            f"📄 既存の領収書金額: ¥{existing_for_t.get('receipt_amount', 0):,}　"
            f"／ 精算額: ¥{existing_for_t.get('approved_amount', 0):,}"
            + (f"　（メモ: {existing_for_t.get('note', '')}）"
               if existing_for_t.get("note") else "")
        )

    # 地域ルール取得
    rules = db.get_transport_rules(event_id) or []
    region, _pref = db.get_staff_region(target["id"])
    rule = next((r for r in rules if r.get("region") == region), None)
    if rule:
        max_amt = int(rule.get("max_amount") or 0)
        is_venue = bool(rule.get("is_venue_region"))
        receipt_required = bool(rule.get("receipt_required"))
        st.caption(
            f"📍 適用ルール（地域: {region or '未設定'}）— "
            f"上限 ¥{max_amt:,}　／ "
            f"開催地: {'はい' if is_venue else 'いいえ'}　／ "
            f"領収書: {'必要' if receipt_required else '不要'}"
        )
    else:
        max_amt = 0
        is_venue = False
        receipt_required = False
        if region:
            st.warning(f"⚠️ 地域 {region} の交通費ルールが未設定です。")
        else:
            st.warning("⚠️ このスタッフの住所から地域が判定できていません。")

    with st.form("pit_transport_form"):
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            receipt_amt = st.number_input(
                "領収書金額（円）",
                min_value=0, step=100,
                value=int((existing_for_t or {}).get("receipt_amount") or 0),
                help="ディーラーから受け取った領収書の合計金額",
            )
        with col_t2:
            has_receipt = st.checkbox(
                "領収書あり",
                value=bool((existing_for_t or {}).get("has_receipt", 1)),
                help="領収書を物理的に受け取ったか",
            )
        t_note = st.text_input(
            "メモ（任意）",
            value=(existing_for_t or {}).get("note", "") or "",
            placeholder="例: 帰路分も含む / Suicaチャージのみ",
        )
        if st.form_submit_button("💾 交通費を保存", type="secondary"):
            # Codex 4回目 P1 #8 fix (2026-05-09): 開催地ルールは max_amount × 勤務日数
            # （3_支払い計算 ページの _calc_transport と挙動を揃える）
            # 出勤予定または出退勤実績のある日数を勤務日数とみなす
            staff_shifts_all = [
                s for s in all_event_shifts
                if s.get("status") != "absent"
            ]
            days_worked = len({s["date"] for s in staff_shifts_all}) or 1

            if is_venue:
                # 開催地: max_amount × 勤務日数 を支給
                approved = max_amt * days_worked
            elif receipt_required and not has_receipt:
                approved = 0  # 領収書必須なのに無し → 精算0
            else:
                # 領収書ベース: min(領収書金額, 上限×勤務日数) または 領収書全額
                if max_amt > 0:
                    approved = min(receipt_amt, max_amt * days_worked)
                else:
                    approved = receipt_amt
            db.upsert_transport_claim(
                event_id=event_id, staff_id=target["id"],
                receipt_amount=int(receipt_amt),
                approved_amount=int(approved),
                has_receipt=int(has_receipt),
                note=t_note,
            )
            db.log_action(
                "pit_transport_claim", "transport_claims", target["id"],
                detail=(
                    f"{target['name_jp']} 領収書¥{receipt_amt:,} "
                    f"→ 精算¥{approved:,}"
                    f"（{days_worked}日分・{'venue' if is_venue else '通常'}）"
                ),
                event_id=event_id,
                performed_by=operator_name(),
            )
            st.success(
                f"💾 交通費を保存しました。"
                f"領収書 ¥{receipt_amt:,} → 精算額 **¥{approved:,}**"
                f"（{days_worked}日分計算）"
            )
            st.rerun()


if not today_shift:
    st.warning(
        f"⚠️ {target['name_jp']} は **{today}** のシフトがありません。"
        "別の日のシフトはこの下に表示されます。"
    )
else:
    cur_status = today_shift.get("status", "scheduled")
    STATUS_DISPLAY = {
        "scheduled": "⬜ 未確定",
        "checked_in": "🟢 出勤中",
        "checked_out": "✅ 退勤済",
        "absent": "❌ 欠勤",
    }
    st.markdown(
        f"**{STATUS_DISPLAY.get(cur_status, cur_status)}**　"
        f"予定 {today_shift.get('planned_start', '—')} 〜 "
        f"{today_shift.get('planned_end', '—')}　"
        f"実績 {today_shift.get('actual_start', '—')} 〜 "
        f"{today_shift.get('actual_end', '—')}"
    )

    if cur_status in ("scheduled", "checked_in"):
        # 退勤打刻フォーム
        with st.form("pit_checkout_form"):
            now_jst = datetime.now(_JST)
            default_hour = now_jst.hour
            default_min = (now_jst.minute // 15) * 15  # 15分丸め
            col_h, col_m = st.columns(2)
            with col_h:
                checkout_hour = st.number_input(
                    "退勤時刻（時）",
                    min_value=0, max_value=29,
                    value=default_hour,
                    help="深夜（24以降）も入力可。例: 25 = 翌日1時",
                )
            with col_m:
                checkout_min = st.selectbox(
                    "退勤時刻（分）",
                    [0, 15, 30, 45],
                    index=[0, 15, 30, 45].index(default_min) if default_min in [0, 15, 30, 45] else 0,
                )
            confirm_pay = st.checkbox(
                "✅ この退勤時刻で支払い計算も同時に実行する（推奨）",
                value=True,
                help="チェックを外すと打刻だけ行います。給与支払い側で別途計算が必要になります。",
            )
            # Phase 3-C (2026-05-08): 承認まで進めるオプション
            # 計算と同時に承認まで進めれば、給与窓口は「支払いボタン押すだけ」に
            _pit_operator_ok = _operator_attributable()
            auto_approve = st.checkbox(
                "🟡 計算と同時に承認まで進める（給与窓口は支払いだけで済む）",
                value=False,
                disabled=not _pit_operator_ok,
                help="ピット側で確認できているなら ON 推奨。"
                "金額が大きい・疑わしいケースは OFF にして給与窓口での承認を残す。"
                "事後的に承認取消も可能（精算レポートから）。",
            )
            if not _pit_operator_ok:
                st.caption(
                    "⚠️ 自動承認にはオペレーター名の設定（再ログイン）が必要です。"
                    "このまま実行すると打刻と支払い計算のみ行います。"
                )
            submitted = st.form_submit_button("🔴 退勤＋支払い確定", type="primary")

            if submitted:
                checkout_time = f"{checkout_hour:02d}:{checkout_min:02d}"
                # 開始時刻が未記録なら予定値を採用（伊藤さん運用パターン）
                actual_start = (
                    today_shift.get("actual_start")
                    or today_shift.get("planned_start")
                )
                client = db.get_client()
                # A-11: 退勤打刻自体を try で囲む。失敗時はここで止め、誤った成功表示を出さない。
                try:
                    client.table("p1_shifts").update({
                        "actual_start": actual_start,
                        "actual_end": checkout_time,
                        "status": "checked_out",
                    }).eq("id", today_shift["id"]).execute()
                    db.log_action(
                        "pit_checkout", "shifts", today_shift["id"],
                        detail=f"{target['name_jp']} (NO.{target.get('no')}) {today} 退勤={checkout_time}",
                        event_id=event_id,
                        performed_by=operator_name(),
                    )
                except Exception as e:
                    st.error(
                        "💥 退勤打刻に失敗しました。通信状況を確認してもう一度お試しください。"
                        "（このスタッフのシフトは未確定のままです）"
                    )
                    with st.expander("🔧 技術詳細"):
                        st.code(str(e))
                    st.stop()

                _checkout_msg = f"✅ {target['name_jp']} を {checkout_time} で退勤確定しました"

                # 支払い計算も実行
                if not confirm_pay:
                    st.success(_checkout_msg)
                else:
                    # A-11: 退勤は確定済み。以降の計算/保存/承認が失敗しても
                    # 「退勤は確定したが支払いは未作成」と明示し、次の人を呼ぶ前に気づけるようにする。
                    try:
                        rates_rows = db.get_event_rates(event_id) or []
                        rates_by_date = {
                            r["date"]: {
                                "hourly": r.get("hourly_rate", 1500),
                                "night": r.get("night_rate", 1875),
                                "transport": r.get("transport_allowance", 1000),
                                "floor_bonus": r.get("floor_bonus", 3000),
                                "mix_bonus": r.get("mix_bonus", 1500),
                            }
                            for r in rates_rows
                        }
                        # 最新シフトを再取得（退勤時刻が反映された状態）
                        latest_shifts = db.get_shifts_for_event(event_id, staff_id=target["id"])
                        shifts_for_calc = []
                        for s in latest_shifts:
                            if s.get("status") == "absent":
                                continue
                            start = s.get("actual_start") or s.get("planned_start")
                            end = s.get("actual_end") or s.get("planned_end")
                            if not start or not end:
                                continue
                            shifts_for_calc.append({
                                "date": s["date"],
                                "start": start,
                                "end": end,
                                "is_mix": bool(s.get("is_mix", 0)),
                            })
                        # Codex P1 fix (2026-05-09): イベント全体の日数を使う
                        # （staff のシフト日数を使うと部分参加でも全勤扱いになり、
                        # 精勤手当 ¥10,000 が誤付与される）
                        total_event_days = len(rates_rows) if rates_rows else len(
                            {s["date"] for s in latest_shifts}
                        )
                        # Phase 3-I: 個別手当を計算に含める（オフレコ含む）
                        individual_allowances = db.get_individual_allowances(
                            event_id, target["id"]
                        )
                        # 交通費が領収書ベースで保存されていれば、それを transport_override に
                        transport_override = None
                        claim = next(
                            (c for c in (db.get_transport_claims(event_id) or [])
                             if c.get("staff_id") == target["id"]),
                            None,
                        )
                        if claim is not None:
                            transport_override = int(claim.get("approved_amount") or 0)
                        # A-5: 既存の臨時調整を保全（ピット再退勤で消さない）
                        _existing_pay = db.get_client().table("p1_payments").select(
                            "adjustment, adjustment_note").eq(
                            "event_id", event_id).eq("staff_id", target["id"]).execute().data
                        _existing_adj = int(_existing_pay[0].get("adjustment") or 0) if _existing_pay else 0
                        _existing_adjnote = (_existing_pay[0].get("adjustment_note") or "") if _existing_pay else ""
                        payment = calculate_staff_payment(
                            staff_id=target["id"],
                            name=target["name_jp"],
                            role=target.get("role", "Dealer"),
                            shifts=shifts_for_calc,
                            rates_by_date=rates_by_date,
                            total_event_days=total_event_days,
                            break_6h=int(event.get("break_minutes_6h") or 0),
                            break_8h=int(event.get("break_minutes_8h") or 0),
                            employment_type=target.get("employment_type") or "contractor",
                            custom_hourly_rate=target.get("custom_hourly_rate"),
                            transport_override=transport_override,
                            individual_allowances=individual_allowances,
                            adjustment=_existing_adj,  # A-5: 既存の臨時調整を引き継ぐ
                        )
                        db.save_payment(
                            event_id=event_id,
                            staff_id=target["id"],
                            base_pay=payment.base_pay,
                            night_pay=payment.night_pay,
                            transport_total=payment.transport_total,
                            floor_bonus_total=payment.floor_bonus_total,
                            mix_bonus_total=payment.mix_bonus_total,
                            attendance_bonus=payment.attendance_bonus,
                            total_amount=payment.total_amount,
                            break_deduction=payment.break_deduction,
                            adjustment=getattr(payment, "adjustment", 0),  # A-5
                            adjustment_note=_existing_adjnote,
                            # Codex P2 fix #3: 個別手当合計を保存
                            individual_allowance_total=getattr(
                                payment, "individual_allowance_total", 0
                            ),
                        )
                        # A-6: 確定額（端数処理後）を表示。封筒・領収書と一致する金額。
                        _pit_payable = db.compute_payable_amount(
                            payment.total_amount, db.get_event_rounding_unit(event_id)
                        )
                        db.log_action(
                            "pit_payment_calc", "payments", target["id"],
                            detail=f"{target['name_jp']} ¥{_pit_payable:,}",
                            event_id=event_id,
                            performed_by=operator_name(),
                        )
                        st.success(
                            _checkout_msg + "\n\n"
                            f"💰 支払い計算も実行しました。"
                            f"確定額 **¥{_pit_payable:,}**（{payment.days_worked}日勤務）"
                        )
                        # UX B: 直前確定カード用の情報を保存
                        st.session_state[_LAST_CONFIRMED_KEY] = {
                            "no": target.get("no", "?"),
                            "name": target["name_jp"],
                            "amount": int(_pit_payable),
                            "checkout": checkout_time,
                            "approved": False,
                        }

                        # Phase 3-C: 承認まで進める（実オペレーター帰属を再確認・防御）
                        if auto_approve and _operator_attributable():
                            # 直近の payment レコードを取得して承認
                            client_q = db.get_client().table("p1_payments").select(
                                "id, status").eq("event_id", event_id).eq(
                                "staff_id", target["id"]).execute().data
                            if client_q:
                                payment_row = client_q[0]
                                payment_id = payment_row["id"]
                                current_status = payment_row.get("status")
                                # Codex P2 fix #4 (2026-05-09): paid を approved に
                                # 退行させないようガード（save_payment は paid 保護するが
                                # approve_payment は別経路なので独立してチェックする）
                                if current_status == "paid":
                                    st.warning(
                                        "⚠️ この支払いは既に **支払済み** です。"
                                        "ピット側からの自動承認はスキップしました。"
                                        "金額の不一致があれば「📊 精算レポート」で確認してください。"
                                    )
                                elif current_status == "approved":
                                    st.info(
                                        "ℹ️ この支払いは既に承認済みでした。"
                                        "再承認の必要はありません。"
                                    )
                                else:
                                    # approve_payment は pending→approved のみ成立し、
                                    # 成否を bool で返す。並走再計算で行が pending でなく
                                    # なっていた場合は False になるため、成功表示はその時だけ。
                                    _approved_ok = db.approve_payment(
                                        payment_id,
                                        approved_by=f"pit:{operator_name()}",
                                        event_id=event_id,
                                    )
                                    if _approved_ok:
                                        st.success(
                                            "🟡 ピット側で承認まで完了しました。"
                                            "給与窓口は「支払いボタンを押すだけ」で OK です。"
                                        )
                                        # UX B: 確定カードに承認済みフラグを反映
                                        if _LAST_CONFIRMED_KEY in st.session_state:
                                            st.session_state[_LAST_CONFIRMED_KEY]["approved"] = True
                                    else:
                                        st.warning(
                                            "⚠️ 自動承認が適用されませんでした"
                                            "（支払いレコードの状態が変化した可能性）。"
                                            "「💰 支払い計算」ページで承認状態を確認してください。"
                                        )
                    except Exception as e:
                        # A-11: 警告は st.rerun() で破棄されるため session_state に退避し、
                        # リラン後にページ上部で再表示する（上の _PIT_ERROR_KEY ブロック）。
                        st.session_state[_PIT_ERROR_KEY] = {
                            "name": target["name_jp"],
                            "detail": str(e),
                        }
                st.rerun()


# ============================================================
# 6. 全期間のシフト一覧 ＋ 試算支払額
# ============================================================
section_header(
    "全期間のシフト＋現時点での試算",
    "イベント全日程の予定／実績を表示。退勤確定済みの分から計算した暫定支払額を試算。",
)

# 表示用テーブル
shift_display = []
for s in all_event_shifts:
    is_today_row = s.get("date") == today
    shift_display.append({
        "今日": "👈" if is_today_row else "",
        "日付": s.get("date", ""),
        "予定": f"{s.get('planned_start', '—')}〜{s.get('planned_end', '—')}",
        "実績": f"{s.get('actual_start', '—')}〜{s.get('actual_end', '—')}",
        "状態": {
            "scheduled": "⬜ 未確定",
            "checked_in": "🟢 出勤中",
            "checked_out": "✅ 退勤済",
            "absent": "❌ 欠勤",
        }.get(s.get("status", ""), s.get("status", "")),
        "MIX": "✓" if s.get("is_mix") else "",
    })
st.dataframe(pd.DataFrame(shift_display), use_container_width=True, hide_index=True)

# 既存の支払い記録がある場合は表示
existing_payments = db.get_payments_for_event(event_id) or []
existing_for_target = next(
    (p for p in existing_payments if p.get("staff_id") == target["id"]), None
)

if existing_for_target:
    st.divider()
    st.markdown("**現在の支払い記録**")
    pay_status = existing_for_target.get("status", "pending")
    PAY_STATUS = {
        "pending": "⬜ 未承認",
        "approved": "🟡 承認済（支払い前）",
        "paid": "✅ 支払済",
    }
    kpi_row([
        {
            "label": "確定支払額",
            "value": f"¥{db.get_payable(existing_for_target):,}",  # A-6: 確定額表示
            "accent": True,
        },
        {
            "label": "ステータス",
            "value": PAY_STATUS.get(pay_status, pay_status),
        },
        {
            "label": "領収書",
            "value": "受領済" if existing_for_target.get("receipt_received") else "未受領",
        },
    ])
    with st.expander("内訳"):
        st.markdown(
            f"- 基本給: ¥{existing_for_target.get('base_pay', 0):,}\n"
            f"- 深夜手当: ¥{existing_for_target.get('night_pay', 0):,}\n"
            f"- 交通費: ¥{existing_for_target.get('transport_total', 0):,}\n"
            f"- フロア手当: ¥{existing_for_target.get('floor_bonus_total', 0):,}\n"
            f"- MIX手当: ¥{existing_for_target.get('mix_bonus_total', 0):,}\n"
            f"- 精勤手当: ¥{existing_for_target.get('attendance_bonus', 0):,}"
        )


# ============================================================
# 7. ピット運用ヒント
# ============================================================
with st.expander("💡 ピット運用のヒント"):
    st.markdown("""
- **NO. を覚えてもらう運用**にしておくと検索が一番早い
- 退勤時刻を確定するときに「支払い計算も同時に実行」（チェック ON）を推奨
- 開始時刻（actual_start）が未記録の場合、予定時刻（planned_start）が自動で入る
- 個別時給があるスタッフは、その時給で計算される（v3.8〜）
- 給与支払い側のオペレーターは「📊 精算レポート」「✉️ 封筒リスト」で「確認だけ」して支払う
""")
