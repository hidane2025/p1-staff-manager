"""勤怠CSV取込（TAKAツール形式）。

フォーマット（1行=1人×1日・ヘッダ必須・BOM可）:
    dealer_number,date,actual_start,actual_end,is_absent
    0055,2026-08-12,12:03,25:17,0
    0277,2026-08-12,,,1        ← 欠勤

ルール（勤怠受信APIと同じ思想・2026-08-14 CLIでの手動取込2回分をUI化）:
    - 冪等: 現在のDBと同じ内容の行は何もしない（再アップロード安全）
    - 支払い済み(paid)・承認済み(approved)のスタッフは変更せず差分を報告だけする
    - シフト行が無い日は新規作成（予定=実績で埋め、支払い計算に載せる）
    - is_absent=1 は欠勤化（行が無ければ何もしない）
    - 反映のたびに本人の支払いを自動再計算（_revert_payment_if_amount_affected 経由）
    - 24時超表記（25:30・30:00）対応。退勤のみ・退勤<出勤・0-48h外は不正行として弾く
"""

from __future__ import annotations

import csv
import io


REQUIRED_COLS = ("dealer_number", "date", "actual_start", "actual_end", "is_absent")


def import_attendance_csv(file_bytes: bytes, event_id: int,
                          performed_by: str = "") -> dict:
    """CSVバイト列を取り込み、結果レポートを返す。例外は呼び出し側で拾う。"""
    import db
    from utils.calculator import parse_time_to_minutes
    from utils.payment_recalc import recalc_staff_payments

    text = file_bytes.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("CSVにデータ行がありません")
    missing = [c for c in REQUIRED_COLS if c not in rows[0]]
    if missing:
        raise ValueError(f"必須列が足りません: {', '.join(missing)}"
                         f"（ヘッダ行: {', '.join(rows[0].keys())}）")

    event_dates = {r["date"] for r in db.get_event_rates(event_id)}
    c = db.get_client()
    smap = {s.get("no"): s for s in db.get_all_staff() if s.get("no")}
    shifts = {}
    for s in db.get_shifts_for_event(event_id):
        shifts[(s["staff_id"], s["date"])] = s
    pays = {p["staff_id"]: p for p in db.get_payments_for_event(event_id)}

    def norm(t):
        t = (t or "").strip()
        if not t:
            return None
        m = parse_time_to_minutes(t)
        if m is None or not (0 <= m < 48 * 60):
            raise ValueError(t)
        return f"{m // 60:02d}:{m % 60:02d}"

    rep = {"total": len(rows), "updated": [], "created": [], "absent": [],
           "noop": 0, "unknown": [], "protected_diff": [], "invalid": [],
           "recalced": 0}
    affected_ids: list = []
    for r in rows:
        try:
            no = int(str(r["dealer_number"]).strip())
        except Exception:
            rep["invalid"].append(f"NO.読めず: {r.get('dealer_number')!r}")
            continue
        date = str(r["date"]).strip()
        if date not in event_dates:
            rep["invalid"].append(f"NO.{no} 対象イベント外の日付: {date}")
            continue
        st_ = smap.get(no)
        if st_ is None:
            rep["unknown"].append(f"NO.{no}")
            continue
        try:
            a_start, a_end = norm(r["actual_start"]), norm(r["actual_end"])
        except ValueError as e:
            rep["invalid"].append(f"NO.{no} 時刻不正: {e}")
            continue
        is_abs = str(r["is_absent"]).strip() == "1"
        if a_end and not a_start:
            rep["invalid"].append(f"NO.{no} 退勤のみ（出勤なし）")
            continue
        if (a_start and a_end
                and parse_time_to_minutes(a_end) < parse_time_to_minutes(a_start)):
            rep["invalid"].append(f"NO.{no} 退勤が出勤より前")
            continue
        row = shifts.get((st_["id"], date))
        pay = pays.get(st_["id"])
        cur = (row.get("actual_start") if row else None,
               row.get("actual_end") if row else None,
               (row.get("status") if row else None) == "absent")
        if row is not None and cur == (a_start, a_end, is_abs):
            rep["noop"] += 1
            continue
        if pay is not None and pay["status"] in ("paid", "approved"):
            rep["protected_diff"].append(
                f"NO.{no} {st_['name_jp']} [{pay['status']}] {date} "
                f"DB={cur[0] or '—'}-{cur[1] or '—'}{'(欠勤)' if cur[2] else ''}"
                f" / CSV={a_start or '—'}-{a_end or '—'}{'(欠勤)' if is_abs else ''}")
            continue
        label = f"NO.{no} {st_['name_jp']}"
        # 金額の再計算は最後にまとめて行う（1人ずつだと人数×10クエリで数分かかる）
        if is_abs:
            if row is None:
                rep["noop"] += 1
                continue
            db.mark_absent(row["id"])  # 内部で差し戻し＋本人再計算まで走る
            rep["absent"].append(label)
        elif row is not None:
            c.table("p1_shifts").update({
                "actual_start": a_start, "actual_end": a_end,
                "status": ("checked_out" if a_end else
                           "checked_in" if a_start else "scheduled"),
            }).eq("id", row["id"]).execute()
            db.reset_payment_to_pending(
                event_id, st_["id"],
                reason=f"勤怠CSV取込 {a_start or '—'}-{a_end or '—'}")
            affected_ids.append(st_["id"])
            rep["updated"].append(label)
        elif a_start is None:
            # 出勤なし・欠勤でもない空行 → 作るものが無い
            rep["noop"] += 1
        else:
            # 2026-08-14 QA修正: 以前は無条件に checked_out で作っていたため、
            # 退勤未定（出勤のみ）の行が「退勤済・退勤時刻なし」になっていた
            c.table("p1_shifts").insert({
                "event_id": event_id, "staff_id": st_["id"], "date": date,
                "planned_start": a_start, "planned_end": a_end or a_start,
                "actual_start": a_start, "actual_end": a_end,
                "status": "checked_out" if a_end else "checked_in",
            }).execute()
            affected_ids.append(st_["id"])
            rep["created"].append(label)

    rep["recalced"] = recalc_staff_payments(event_id, affected_ids)

    db.log_action(
        "attendance_csv_import", "shifts",
        detail=(f"勤怠CSV取込: 更新{len(rep['updated'])}・新規{len(rep['created'])}"
                f"・欠勤{len(rep['absent'])}・一致{rep['noop']}"
                f"・保護差分{len(rep['protected_diff'])}"
                f"・未登録{len(rep['unknown'])}・不正{len(rep['invalid'])}"),
        event_id=event_id, performed_by=performed_by or "csv_import")
    return rep
