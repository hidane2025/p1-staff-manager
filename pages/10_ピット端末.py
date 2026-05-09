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
from utils.admin_guard import require_admin, admin_logout_button, operator_name


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

# 今日の日付（JST）
today = datetime.now(_JST).strftime("%Y-%m-%d")
today_shift = next((s for s in all_event_shifts if s.get("date") == today), None)

# ============================================================
# 4. スタッフ情報サマリー
# ============================================================
section_header(f"👤 {target['name_jp']}（NO.{target.get('no')}）")

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
custom_rate_display = f"¥{custom_rate:,}" if custom_rate else "—"

kpi_row([
    {"label": "役職", "value": target.get("role", "—")},
    {"label": "雇用区分", "value": emp_label},
    {"label": "個別時給", "value": custom_rate_display, "detail": "0=イベント基本時給"},
])

# Phase 3-I: 個別手当の状態を表示（オフレコ手当は内訳非表示）
indiv_allowances = db.get_individual_allowances(event_id, target["id"])
if indiv_allowances:
    open_count = sum(1 for a in indiv_allowances if not a.get("is_off_record"))
    off_count = sum(1 for a in indiv_allowances if a.get("is_off_record"))
    open_total = sum(int(a.get("amount") or 0) for a in indiv_allowances if not a.get("is_off_record"))
    # オフレコは合計だけ含めるが、ピット端末では金額・件数を伏せる
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
            # 精算額を算出: 開催地ルールなら一律 max_amount、それ以外は min(領収書金額, 上限)
            if is_venue:
                approved = max_amt
            elif receipt_required and not has_receipt:
                approved = 0  # 領収書必須なのに無し → 精算0
            else:
                approved = min(receipt_amt, max_amt) if max_amt > 0 else receipt_amt
            db.upsert_transport_claim(
                event_id=event_id, staff_id=target["id"],
                receipt_amount=int(receipt_amt),
                approved_amount=int(approved),
                has_receipt=int(has_receipt),
                note=t_note,
            )
            db.log_action(
                "pit_transport_claim", "transport_claims", target["id"],
                detail=f"{target['name_jp']} 領収書¥{receipt_amt:,} → 精算¥{approved:,}",
                event_id=event_id,
                performed_by=operator_name(),
            )
            st.success(
                f"💾 交通費を保存しました。"
                f"領収書 ¥{receipt_amt:,} → 精算額 **¥{approved:,}**"
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
            auto_approve = st.checkbox(
                "🟡 計算と同時に承認まで進める（給与窓口は支払いだけで済む）",
                value=False,
                help="ピット側で確認できているなら ON 推奨。"
                "金額が大きい・疑わしいケースは OFF にして給与窓口での承認を残す。"
                "事後的に承認取消も可能（精算レポートから）。",
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
                st.success(f"✅ {target['name_jp']} を {checkout_time} で退勤確定しました")

                # 支払い計算も実行
                if confirm_pay:
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
                        # Codex P2 fix #3: 個別手当合計を保存
                        individual_allowance_total=getattr(
                            payment, "individual_allowance_total", 0
                        ),
                    )
                    db.log_action(
                        "pit_payment_calc", "payments", target["id"],
                        detail=f"{target['name_jp']} ¥{payment.total_amount:,}",
                        event_id=event_id,
                        performed_by=operator_name(),
                    )
                    st.success(
                        f"💰 支払い計算も実行しました。"
                        f"合計 **¥{payment.total_amount:,}**（{payment.days_worked}日勤務）"
                    )

                    # Phase 3-C: 承認まで進める
                    if auto_approve:
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
                                db.approve_payment(
                                    payment_id,
                                    approved_by=f"pit:{operator_name()}",
                                    event_id=event_id,
                                )
                                st.success(
                                    "🟡 ピット側で承認まで完了しました。"
                                    "給与窓口は「支払いボタンを押すだけ」で OK です。"
                                )
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
            "label": "合計支払額",
            "value": f"¥{existing_for_target.get('total_amount', 0):,}",
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
