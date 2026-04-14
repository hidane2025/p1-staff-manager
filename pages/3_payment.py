"""P1 Staff Manager — 支払い計算ページ v2
承認フロー: 計算 → 承認 → 支払い
領収書連動: 領収書未受領 → 支払い不可
"""

import streamlit as st
import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.calculator import calculate_staff_payment

st.set_page_config(page_title="支払い計算", page_icon="💰", layout="wide")
st.title("💰 支払い計算")

# --- イベント選択 ---
events = db.get_all_events()
if not events:
    st.warning("イベントがありません。シフト取込ページでイベントを作成してください。")
    st.stop()

event_options = {f"{e['name']} ({e['start_date']}〜{e['end_date']})": e["id"] for e in events}
selected = st.selectbox("イベント選択", list(event_options.keys()))
event_id = event_options[selected]
event = db.get_event_by_id(event_id)

# レートと日数
rates = db.get_event_rates(event_id)
total_event_days = len(rates) if rates else 6

rates_by_date = {}
for r in rates:
    rates_by_date[r["date"]] = {
        "hourly": r["hourly_rate"],
        "night": r["night_rate"],
        "transport": r["transport_allowance"],
        "floor_bonus": r["floor_bonus"],
        "mix_bonus": r["mix_bonus"],
    }

# 休憩設定
break_6h = event.get("break_minutes_6h", 45) if event else 45
break_8h = event.get("break_minutes_8h", 60) if event else 60

# --- 計算実行 ---
st.divider()
st.markdown(f"**休憩控除:** 6h超={break_6h}分 / 8h超={break_8h}分")

if st.button("🔄 支払い額を計算", type="primary"):
    shifts = db.get_shifts_for_event(event_id)
    if not shifts:
        st.warning("シフトが登録されていません。先にシフト取込を行ってください。")
        st.stop()

    # 支払済み・承認済みスタッフの確認
    existing_payments = db.get_payments_for_event(event_id)
    protected_ids = {p["staff_id"] for p in existing_payments if p["status"] in ("paid", "approved")}
    if protected_ids:
        st.warning(f"⚠️ {len(protected_ids)}名が承認済み/支払済みです。スキップします。")

    # スタッフごとにグループ化
    staff_shifts = {}
    for s in shifts:
        key = s["staff_id"]
        if key not in staff_shifts:
            staff_shifts[key] = {"name": s["name_jp"], "role": s["role"], "shifts": []}
        if s["status"] == "absent":
            continue
        if s["planned_start"] and s["planned_end"]:
            start = s.get("actual_start") or s["planned_start"]
            end = s.get("actual_end") or s["planned_end"]
            staff_shifts[key]["shifts"].append({
                "date": s["date"],
                "start": start,
                "end": end,
                "is_mix": bool(s.get("is_mix", 0)),
            })

    results = []
    skipped = 0
    for staff_id, data in staff_shifts.items():
        if staff_id in protected_ids:
            skipped += 1
            continue
        payment = calculate_staff_payment(
            staff_id=staff_id, name=data["name"], role=data["role"],
            shifts=data["shifts"], rates_by_date=rates_by_date,
            total_event_days=total_event_days,
            break_6h=break_6h, break_8h=break_8h,
        )
        results.append(payment)
        db.save_payment(
            event_id=event_id, staff_id=staff_id,
            base_pay=payment.base_pay, night_pay=payment.night_pay,
            transport_total=payment.transport_total,
            floor_bonus_total=payment.floor_bonus_total,
            mix_bonus_total=payment.mix_bonus_total,
            attendance_bonus=payment.attendance_bonus,
            break_deduction=payment.break_deduction,
            total_amount=payment.total_amount,
        )

    msg = f"{len(results)}名の支払い額を計算・保存しました"
    if skipped:
        msg += f"（承認/支払済み{skipped}名はスキップ）"
    st.success(msg)

# --- 結果表示 ---
payments = db.get_payments_for_event(event_id)

if not payments:
    st.info("支払いデータがありません。上の「支払い額を計算」ボタンを押してください。")
    st.stop()

# --- サマリー ---
st.subheader("支払い一覧")
total_all = sum(p["total_amount"] for p in payments)
pending_count = sum(1 for p in payments if p["status"] == "pending")
approved_count = sum(1 for p in payments if p["status"] == "approved")
paid_count = sum(1 for p in payments if p["status"] == "paid")

col1, col2, col3, col4 = st.columns(4)
col1.metric("総支払額", f"¥{total_all:,}")
col2.metric("⏳ 未承認", f"{pending_count}名")
col3.metric("✅ 承認済", f"{approved_count}名")
col4.metric("💴 支払済", f"{paid_count}名")

st.divider()
st.markdown("**支払い内訳合計:**")
row1 = st.columns(3)
row1[0].metric("基本給", f"¥{sum(p['base_pay'] for p in payments):,}")
row1[1].metric("深夜手当", f"¥{sum(p['night_pay'] for p in payments):,}")
row1[2].metric("交通費", f"¥{sum(p['transport_total'] for p in payments):,}")
row2 = st.columns(3)
row2[0].metric("フロア手当", f"¥{sum(p['floor_bonus_total'] for p in payments):,}")
row2[1].metric("MIX手当", f"¥{sum(p['mix_bonus_total'] for p in payments):,}")
row2[2].metric("精勤手当", f"¥{sum(p['attendance_bonus'] for p in payments):,}")

# 休憩控除合計
total_break = sum(p.get("break_deduction", 0) for p in payments)
if total_break > 0:
    st.info(f"休憩控除合計: ¥{total_break:,}（基本給から控除済み）")

st.divider()

# --- 承認フロー ---
st.subheader("承認・支払い")
st.markdown("""
**フロー:** 計算（⏳未承認）→ 承認（✅承認済）→ 領収書受領 → 支払い（💴支払済）
""")

# 承認者入力
approver = st.text_input("承認者名", placeholder="例: 半谷", key="approver_name")

col_approve, col_pay = st.columns(2)

with col_approve:
    pending_payments = [p for p in payments if p["status"] == "pending"]
    if pending_payments and approver:
        if st.button(f"✅ 未承認{len(pending_payments)}名を一括承認", type="primary"):
            for p in pending_payments:
                db.approve_payment(p["id"], approver, event_id)
            st.success(f"{len(pending_payments)}名を承認しました（承認者: {approver}）")
            st.rerun()
    elif pending_payments:
        st.info("承認者名を入力してから承認ボタンを押してください")

with col_pay:
    approved_payments = [p for p in payments if p["status"] == "approved"]
    payable = [p for p in approved_payments if p["receipt_received"]]
    not_payable = [p for p in approved_payments if not p["receipt_received"]]
    if payable:
        if st.button(f"💴 承認済み＋領収書受領済みの{len(payable)}名を支払済みに"):
            for p in payable:
                db.mark_paid(p["id"], event_id)
            st.success(f"{len(payable)}名を支払済みにしました")
            st.rerun()
    if not_payable:
        st.warning(f"⚠️ {len(not_payable)}名が承認済みだが領収書未受領のため支払い不可")

st.divider()

# --- フィルタ ---
col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
with col_f1:
    search = st.text_input("🔍 名前で検索", key="payment_search")
with col_f2:
    role_filter = st.selectbox("役職", ["すべて", "Dealer", "Floor", "TD", "DC", "Chip"], key="payment_role")
with col_f3:
    status_filter = st.selectbox("状態", ["すべて", "⏳ 未承認", "✅ 承認済", "💴 支払済"], key="payment_status")

filtered = payments
if search:
    filtered = [p for p in filtered if search.lower() in p["name_jp"].lower()]
if role_filter != "すべて":
    filtered = [p for p in filtered if p["role"] == role_filter]
status_map = {"⏳ 未承認": "pending", "✅ 承認済": "approved", "💴 支払済": "paid"}
if status_filter != "すべて":
    filtered = [p for p in filtered if p["status"] == status_map[status_filter]]

# --- テーブル ---
display_data = []
for p in filtered:
    status_icon = {"pending": "⏳ 未承認", "approved": "✅ 承認済", "paid": "💴 支払済"}.get(p["status"], p["status"])
    display_data.append({
        "NO.": p["no"], "名前": p["name_jp"], "役職": p["role"],
        "基本給": f"¥{p['base_pay']:,}", "深夜": f"¥{p['night_pay']:,}",
        "交通費": f"¥{p['transport_total']:,}", "Floor": f"¥{p['floor_bonus_total']:,}",
        "MIX": f"¥{p['mix_bonus_total']:,}", "精勤": f"¥{p['attendance_bonus']:,}",
        "合計": f"¥{p['total_amount']:,}",
        "状態": status_icon, "領収書": "✅" if p["receipt_received"] else "❌",
    })

st.dataframe(pd.DataFrame(display_data), use_container_width=True, hide_index=True)

# --- 個別操作 ---
st.divider()
st.subheader("個別スタッフ操作")
staff_opts = {f"NO.{p['no']} {p['name_jp']} ({p['role']}) — ¥{p['total_amount']:,}": p for p in filtered}
if staff_opts:
    sel = st.selectbox("スタッフを選択", list(staff_opts.keys()))
    p = staff_opts[sel]

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.markdown(f"""
**{p['name_jp']}** (NO.{p['no']}) — {p['role']}

| 項目 | 金額 |
|------|------|
| 基本給 | ¥{p['base_pay']:,} |
| 深夜手当 | ¥{p['night_pay']:,} |
| 休憩控除 | -¥{p.get('break_deduction', 0):,} |
| 交通費 | ¥{p['transport_total']:,} |
| フロア手当 | ¥{p['floor_bonus_total']:,} |
| MIX手当 | ¥{p['mix_bonus_total']:,} |
| 精勤手当 | ¥{p['attendance_bonus']:,} |
| **合計** | **¥{p['total_amount']:,}** |

承認者: {p.get('approved_by') or '未承認'}
""")

    with col_d2:
        # 承認
        if p["status"] == "pending":
            if approver:
                if st.button("✅ この人を承認", key=f"approve_{p['id']}"):
                    db.approve_payment(p["id"], approver, event_id)
                    st.success(f"{p['name_jp']} を承認しました")
                    st.rerun()
            else:
                st.info("承認者名を入力してください")

        # 領収書
        if not p["receipt_received"]:
            if st.button("🧾 領収書受領済み", key=f"receipt_{p['id']}"):
                db.mark_receipt_received(p["id"], event_id)
                st.success(f"{p['name_jp']} の領収書を受領しました")
                st.rerun()
        else:
            st.success("領収書受領済み ✅")

        # 支払い（承認済み＋領収書受領済みのみ）
        if p["status"] == "approved":
            if p["receipt_received"]:
                if st.button("💴 支払済みにする", key=f"pay_{p['id']}"):
                    db.mark_paid(p["id"], event_id)
                    st.success(f"{p['name_jp']} を支払済みにしました")
                    st.rerun()
            else:
                st.error("❌ 領収書が未受領のため支払いできません")
        elif p["status"] == "paid":
            st.success("支払済み 💴")

# --- 監査ログ ---
st.divider()
st.subheader("📝 操作ログ（直近20件）")
logs = db.get_audit_log(event_id=event_id, limit=20)
if logs:
    log_display = [{
        "日時": l["created_at"],
        "操作": l["action"],
        "対象": l["target_type"],
        "詳細": l["detail"] or "",
        "実行者": l["performed_by"],
    } for l in logs]
    st.dataframe(pd.DataFrame(log_display), use_container_width=True, hide_index=True)
else:
    st.info("操作ログはまだありません")
