"""1人分の支払い再計算（出退勤の変更に金額を追随させる）。

2026-08-13 追加の経緯:
    出退勤の実績変更・欠勤マークは支払いを「未承認に差し戻す」だけで、
    金額そのものは次に支払い計算ボタンを押すまで古いままだった。
    大会現場で「8/13を欠勤にしたのに封筒額が2日分のまま」（NO.496）が起き、
    清算デスクが古い金額で現金を渡しかねないため、変更の瞬間に
    その1人だけを再計算して保存する。

計算経路は pages/3_payment の一括計算と完全に同じ
（actual優先→calculate_staff_payment→save_payment）。
"""

from __future__ import annotations


def recalc_staff_payment(event_id, staff_id) -> bool:
    """現在のシフト実態からその人の支払いを再計算して保存する。

    - 支払い行が無い（未計算）場合は何もしない（計算ボタンの初回計算に任せる）
    - paid / approved は触らない（打刻側の reset_payment_to_pending が
      approved を pending に戻した後に呼ばれる想定）
    - 打刻処理の途中から呼ばれるため、例外は投げず False を返す

    Returns:
        True = 再計算・保存した / False = 対象外または失敗
    """
    try:
        import db
        from utils.calculator import calculate_staff_payment
        from utils import transport_rules

        prev = next((p for p in db.get_payments_for_event(event_id)
                     if p["staff_id"] == staff_id), None)
        if prev is None or prev["status"] in ("paid", "approved"):
            return False

        ev = db.get_event_by_id(event_id)
        if not ev:
            return False
        staff = next((s for s in db.get_all_staff() if s["id"] == staff_id), None)
        if staff is None:
            return False

        rates = {r["date"]: r for r in db.get_event_rates(event_id)}
        rates_by_date = {
            d: {"hourly": r["hourly_rate"], "night": r["night_rate"],
                "transport": r["transport_allowance"],
                "floor_bonus": r["floor_bonus"], "mix_bonus": r["mix_bonus"]}
            for d, r in rates.items()
        }
        shifts = []
        for s in db.get_shifts_for_event(event_id):
            # 2026-08-13 中野さん方針: 打刻（実到着・実退勤）が揃った日だけを
            # 支払いに入れる。予定のみ・出勤中の日は¥0（pages/3 の一括計算と同一ルール）
            if (s["staff_id"] != staff_id or s["status"] == "absent"
                    or not (s.get("actual_start") and s.get("actual_end"))):
                continue
            shifts.append({
                "date": s["date"],
                "start": s["actual_start"],
                "end": s["actual_end"],
                "is_mix": bool(s.get("is_mix", 0)),
            })
        shifts.sort(key=lambda x: x["date"])

        rules = {r["region"]: r for r in db.get_transport_rules(event_id)}
        claims = {c["staff_id"]: c for c in db.get_transport_claims(event_id)}
        transport_override, _ = transport_rules.payment_amount(
            rules, staff.get("region"), len(shifts), claims.get(staff_id))

        payment = calculate_staff_payment(
            staff_id=staff_id, name=staff["name_jp"],
            role=staff.get("role") or "Dealer",
            shifts=shifts, rates_by_date=rates_by_date,
            total_event_days=len(rates),
            break_6h=ev["break_minutes_6h"], break_8h=ev["break_minutes_8h"],
            employment_type=staff.get("employment_type") or "contractor",
            custom_hourly_rate=staff.get("custom_hourly_rate"),
            transport_override=transport_override,
            individual_allowances=db.get_individual_allowances(event_id, staff_id),
            adjustment=int(prev.get("adjustment") or 0),
        )
        db.save_payment(
            event_id=event_id, staff_id=staff_id,
            base_pay=payment.base_pay, night_pay=payment.night_pay,
            transport_total=payment.transport_total,
            floor_bonus_total=payment.floor_bonus_total,
            mix_bonus_total=payment.mix_bonus_total,
            attendance_bonus=payment.attendance_bonus,
            break_deduction=payment.break_deduction,
            total_amount=payment.total_amount,
            adjustment=getattr(payment, "adjustment", 0),
            adjustment_note=prev.get("adjustment_note") or "",
            individual_allowance_total=getattr(
                payment, "individual_allowance_total", 0),
        )
        return True
    except Exception:
        return False
