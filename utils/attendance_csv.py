"""勤怠CSV取込（TAKAツール形式）。

フォーマット（1行=1人×1日・ヘッダ必須・BOM可）:
    dealer_number,date,actual_start,actual_end,is_absent
    0055,2026-08-12,12:03,25:17,0
    0277,2026-08-12,,,1        ← 欠勤

任意列 `is_mix`（0/1・2026-08-14追加）:
    その日MIX卓に入った人は 1 → MIX手当（日当）が支払いに乗る。
    列が無いCSV・空欄は「変更しない」（既存のMIXフラグを保持）。

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

# APL（韓国）側の運営スタッフ番号。支払いはAPL側管理のため当ツールの対象外
# （2026-08-14 中野さん確定「A韓国側 B韓国側 払わない」）。
# TAKAツールのCSVには混ざってくるため、警告ではなく「対象外」として静かに区別する。
# ※Casper(1006)・台湾Dealer(1011-1014)は当方支払いのため含めない。
APL_EXTERNAL_NOS = {1001, 1002, 1003, 1004, 1005, 1007, 1008, 1009, 1010}


def import_attendance_csv(file_bytes: bytes, event_id: int,
                          performed_by: str = "",
                          overwrite_manual: bool = False) -> dict:
    """CSVバイト列を取り込み、結果レポートを返す。例外は呼び出し側で拾う。

    overwrite_manual（2026-08-15 中野さん指示で追加・既定False）:
        False = 手入力保護モード。既に実績（実到着/実退勤）や欠勤が入っている行は
                CSVが違う値を持っていても**変更しない**（差分は kept_manual に報告）。
                空の行を埋める・行を新規作成する・MIXフラグを反映するだけ。
        True  = 従来どおりCSVを正として上書き（TAKAデータで一括修正したい時だけ）。
    """
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
           "external": [], "kept_manual": [], "mix_only": [], "recalced": 0}
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
            if no in APL_EXTERNAL_NOS:
                rep["external"].append(f"NO.{no}")
            else:
                rep["unknown"].append(f"NO.{no}")
            continue
        try:
            a_start, a_end = norm(r["actual_start"]), norm(r["actual_end"])
        except ValueError as e:
            rep["invalid"].append(f"NO.{no} 時刻不正: {e}")
            continue
        is_abs = str(r["is_absent"]).strip() == "1"
        # 任意列 is_mix: "1"/"0"のみ解釈。空欄・列なしは None=変更しない
        _mix_raw = str(r.get("is_mix") or "").strip()
        want_mix = 1 if _mix_raw == "1" else 0 if _mix_raw == "0" else None
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
        cur_mix = int(row.get("is_mix") or 0) if row else 0
        mix_changed = (want_mix is not None and row is not None
                       and want_mix != cur_mix)
        if row is not None and cur == (a_start, a_end, is_abs) and not mix_changed:
            rep["noop"] += 1
            continue
        if pay is not None and pay["status"] in ("paid", "approved"):
            rep["protected_diff"].append(
                f"NO.{no} {st_['name_jp']} [{pay['status']}] {date} "
                f"DB={cur[0] or '—'}-{cur[1] or '—'}{'(欠勤)' if cur[2] else ''}"
                f" / CSV={a_start or '—'}-{a_end or '—'}{'(欠勤)' if is_abs else ''}")
            continue
        label = f"NO.{no} {st_['name_jp']}"
        # 手入力保護モード（既定）: 実績や欠勤が既に入っている行は時刻・欠勤を変えない。
        # 画面・ピットで打った記録をCSVが黙って潰す事故の防止（2026-08-15 中野さん指示）。
        # MIXフラグだけはTAKAツールが唯一の情報源なので、保護モードでも反映する。
        _has_manual = row is not None and (
            row.get("actual_start") or row.get("actual_end")
            or row.get("status") == "absent")
        if not overwrite_manual and _has_manual:
            if mix_changed:
                c.table("p1_shifts").update(
                    {"is_mix": want_mix}).eq("id", row["id"]).execute()
                db.reset_payment_to_pending(
                    event_id, st_["id"], reason="勤怠CSV取込・MIXフラグのみ反映")
                affected_ids.append(st_["id"])
                rep["mix_only"].append(label)
            if cur != (a_start, a_end, is_abs):
                rep["kept_manual"].append(
                    f"{label} {date} 手入力={cur[0] or '—'}-{cur[1] or '—'}"
                    f"{'(欠勤)' if cur[2] else ''}"
                    f" / CSV={a_start or '—'}-{a_end or '—'}{'(欠勤)' if is_abs else ''}")
            elif not mix_changed:
                rep["noop"] += 1
            continue
        # 金額の再計算は最後にまとめて行う（1人ずつだと人数×10クエリで数分かかる）
        if is_abs:
            if row is None:
                rep["noop"] += 1
                continue
            db.mark_absent(row["id"])  # 内部で差し戻し＋本人再計算まで走る
            rep["absent"].append(label)
        elif row is not None:
            _upd = {
                "actual_start": a_start, "actual_end": a_end,
                "status": ("checked_out" if a_end else
                           "checked_in" if a_start else "scheduled"),
            }
            if want_mix is not None:
                _upd["is_mix"] = want_mix
            c.table("p1_shifts").update(_upd).eq("id", row["id"]).execute()
            db.reset_payment_to_pending(
                event_id, st_["id"],
                reason=f"勤怠CSV取込 {a_start or '—'}-{a_end or '—'}"
                       + ("・MIX変更" if mix_changed else ""))
            affected_ids.append(st_["id"])
            rep["updated"].append(label + ("〔MIX〕" if want_mix == 1 else ""))
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
                "is_mix": want_mix or 0,
            }).execute()
            affected_ids.append(st_["id"])
            rep["created"].append(label + ("〔MIX〕" if want_mix == 1 else ""))

    rep["recalced"] = recalc_staff_payments(event_id, affected_ids)

    db.log_action(
        "attendance_csv_import", "shifts",
        detail=(f"勤怠CSV取込({'上書き' if overwrite_manual else '手入力保護'}): "
                f"更新{len(rep['updated'])}・新規{len(rep['created'])}"
                f"・欠勤{len(rep['absent'])}・一致{rep['noop']}"
                f"・手入力保持{len(rep['kept_manual'])}・MIXのみ{len(rep['mix_only'])}"
                f"・保護差分{len(rep['protected_diff'])}"
                f"・未登録{len(rep['unknown'])}・不正{len(rep['invalid'])}"
                f"・APL対象外{len(rep['external'])}"),
        event_id=event_id, performed_by=performed_by or "csv_import")
    return rep
