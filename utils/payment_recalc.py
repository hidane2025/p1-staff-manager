"""支払い再計算（出退勤の変更に金額を追随させる）。

2026-08-13 追加の経緯:
    出退勤の実績変更・欠勤マークは支払いを「未承認に差し戻す」だけで、
    金額そのものは次に支払い計算ボタンを押すまで古いままだった。
    大会現場で「8/13を欠勤にしたのに封筒額が2日分のまま」（NO.496）が起き、
    清算デスクが古い金額で現金を渡しかねないため、変更の瞬間に再計算して保存する。

2026-08-14 バッチ化:
    CSV取込・全員退勤など複数人が一度に変わる処理が「1人ずつ再計算」だと
    人数×約10クエリで数分かかるため、イベント全体の文脈（レート・交通費ルール・
    手当・全シフト）を1回だけ取得して使い回すバッチ版を追加した。

計算経路は pages/3_payment の一括計算と完全に同じ
（打刻済みの日のみ→actual→calculate_staff_payment→save_payment）。
"""

from __future__ import annotations


def _build_context(event_id):
    """イベント全体の計算文脈を1回のフェッチ群で組む。"""
    import db

    ev = db.get_event_by_id(event_id)
    if not ev:
        return None
    rates = {r["date"]: r for r in db.get_event_rates(event_id)}
    allowances = {}
    for a in db.get_individual_allowances(event_id):
        allowances.setdefault(a["staff_id"], []).append(a)
    shifts_by_staff = {}
    for s in db.get_shifts_for_event(event_id):
        # 支払い対象は打刻（実到着・実退勤）が揃った日だけ（2026-08-13 中野さん方針）
        if s["status"] == "absent" or not (s.get("actual_start") and s.get("actual_end")):
            continue
        shifts_by_staff.setdefault(s["staff_id"], []).append({
            "date": s["date"], "start": s["actual_start"], "end": s["actual_end"],
            "is_mix": bool(s.get("is_mix", 0)),
        })
    return {
        "ev": ev,
        "rates": rates,
        "rates_by_date": {
            d: {"hourly": r["hourly_rate"], "night": r["night_rate"],
                "transport": r["transport_allowance"],
                "floor_bonus": r["floor_bonus"], "mix_bonus": r["mix_bonus"]}
            for d, r in rates.items()},
        "rules": {r["region"]: r for r in db.get_transport_rules(event_id)},
        "claims": {c["staff_id"]: c for c in db.get_transport_claims(event_id)},
        "allowances": allowances,
        "shifts_by_staff": shifts_by_staff,
        "staff_by_id": {s["id"]: s for s in db.get_all_staff()},
        "payments": {p["staff_id"]: p for p in db.get_payments_for_event(event_id)},
    }


def _recalc_one(event_id, staff_id, ctx) -> bool:
    """文脈を使い回して1人分を再計算・保存。対象外はFalse。"""
    import db
    from utils.calculator import calculate_staff_payment
    from utils import transport_rules

    prev = ctx["payments"].get(staff_id)
    if prev is None or prev["status"] in ("paid", "approved"):
        return False
    staff = ctx["staff_by_id"].get(staff_id)
    if staff is None:
        return False
    shifts = sorted(ctx["shifts_by_staff"].get(staff_id, []),
                    key=lambda x: x["date"])
    transport_override, _ = transport_rules.payment_amount(
        ctx["rules"], staff.get("region"), len(shifts),
        ctx["claims"].get(staff_id))
    payment = calculate_staff_payment(
        staff_id=staff_id, name=staff["name_jp"],
        role=staff.get("role") or "Dealer",
        shifts=shifts, rates_by_date=ctx["rates_by_date"],
        total_event_days=len(ctx["rates"]),
        break_6h=ctx["ev"]["break_minutes_6h"], break_8h=ctx["ev"]["break_minutes_8h"],
        employment_type=staff.get("employment_type") or "contractor",
        custom_hourly_rate=staff.get("custom_hourly_rate"),
        transport_override=transport_override,
        individual_allowances=ctx["allowances"].get(staff_id, []),
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


def recalc_staff_payments(event_id, staff_ids) -> int:
    """複数人をまとめて再計算（文脈は1回だけ取得）。戻り値=保存した人数。

    打刻処理・取込処理から呼ばれるため例外は投げない。
    """
    done = 0
    try:
        ids = [s for s in dict.fromkeys(staff_ids) if s is not None]
        if not ids:
            return 0
        ctx = _build_context(event_id)
        if ctx is None:
            return 0
        for sid in ids:
            try:
                if _recalc_one(event_id, sid, ctx):
                    done += 1
            except Exception:
                continue
    except Exception:
        pass
    return done


def recalc_staff_payment(event_id, staff_id) -> bool:
    """1人分の再計算（従来API・打刻フックから使用）。

    - 支払い行が無い（未計算）場合は何もしない（計算ボタンの初回計算に任せる）
    - paid / approved は触らない（打刻側の reset_payment_to_pending が
      approved を pending に戻した後に呼ばれる想定）
    - 例外は投げず False を返す
    """
    return recalc_staff_payments(event_id, [staff_id]) == 1
