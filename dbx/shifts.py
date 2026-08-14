"""シフト・出退勤・配布チェック（db.py から2026-08-06に機械分割・挙動不変）"""
import os
import re
import unicodedata
import streamlit as st
from datetime import datetime, timezone, timedelta
from typing import Optional
try:
    from supabase import create_client
except ImportError:
    create_client = None

from dbx import core
from dbx.core import _flatten_staff_join
from dbx.payments import reset_payment_to_pending


# === Shifts ===

def upsert_shift(event_id, staff_id, date, planned_start, planned_end, is_mix=0):
    client = core.get_client()
    existing = client.table("p1_shifts").select(
        "id, planned_start, planned_end, is_mix, event_id, staff_id"
    ).eq("event_id", event_id).eq("staff_id", staff_id).eq("date", date).execute()
    if existing.data:
        _old = existing.data[0]
        client.table("p1_shifts").update({
            "planned_start": planned_start, "planned_end": planned_end, "is_mix": is_mix
        }).eq("id", _old["id"]).execute()
        # 2026-08-04: シフト再取込で予定時刻やMIX区分が変わった場合も、打刻経路
        # （checkin/checkout/欠勤）と同じく承認済み支払いを未承認へ差し戻す。
        # ここだけガードが無く、承認後にシフトを再取込すると承認済みの金額が
        # 古いまま黙って残っていた（UI運用テスト第3弾で実測）。支払済みは
        # reset_payment_to_pending 側が保護する。
        if (str(_old.get("planned_start")) != str(planned_start)
                or str(_old.get("planned_end")) != str(planned_end)
                or int(_old.get("is_mix") or 0) != int(is_mix or 0)):
            _revert_payment_if_amount_affected(
                _old,
                reason=f"シフト再取込で予定変更 {planned_start}〜{planned_end}（要再計算）",
            )
    else:
        client.table("p1_shifts").insert({
            "event_id": event_id, "staff_id": staff_id, "date": date,
            "planned_start": planned_start, "planned_end": planned_end, "is_mix": is_mix
        }).execute()


def get_shifts_for_event(event_id, date=None, staff_id=None):
    client = core.get_client()
    q = client.table("p1_shifts").select("*, p1_staff(name_jp, name_en, no, role)").eq("event_id", event_id)
    if date:
        q = q.eq("date", date)
    if staff_id:
        q = q.eq("staff_id", staff_id)
    data = q.order("staff_id").execute().data
    return _flatten_staff_join(data)


def _revert_payment_if_amount_affected(shift_row, reason: str) -> None:
    """出退勤の実績変更が支払い額に影響し得るとき、支払いを差し戻して即再計算する。

    凍結退勤と同じ内部統制（reset_payment_to_pending。支払済みは保護）を
    欠勤・遅刻・早退・延長にも適用する（2026-07-06 追加）。
    2026-08-13: 差し戻しだけでは金額が古いまま清算デスクに出てしまう
    （NO.496 欠勤マーク後も2日分の封筒額が表示された）ため、
    その場でこの1人だけを再計算・保存するところまで行う。
    支払い未計算・列欠損などの失敗は握りつぶし、本処理（打刻）は壊さない。
    """
    try:
        ev = shift_row.get("event_id")
        sid = shift_row.get("staff_id")
        if ev and sid:
            reset_payment_to_pending(ev, sid, reason=reason)
            from utils.payment_recalc import recalc_staff_payment
            recalc_staff_payment(ev, sid)
    except Exception:
        pass


def checkin_staff(shift_id, actual_start):
    client = core.get_client()
    row = client.table("p1_shifts").select(
        "status, actual_end, planned_start, event_id, staff_id"
    ).eq("id", shift_id).execute().data
    if row and row[0].get("actual_end"):
        client.table("p1_shifts").update({"actual_start": actual_start}).eq("id", shift_id).execute()
    else:
        client.table("p1_shifts").update({
            "actual_start": actual_start, "status": "checked_in"
        }).eq("id", shift_id).execute()
    # 2026-08-13 打刻済ルール移行: 予定どおりの打刻でも「¥0→満額」の変化になるため、
    # 予定と同じ時刻かどうかに関わらず常に差し戻し＋再計算する
    if row:
        _revert_payment_if_amount_affected(row[0], reason=f"到着実績 {actual_start} 記録（要再計算）")


def checkout_staff(shift_id, actual_end):
    client = core.get_client()
    row = client.table("p1_shifts").select(
        "planned_end, event_id, staff_id"
    ).eq("id", shift_id).execute().data
    client.table("p1_shifts").update({
        "actual_end": actual_end, "status": "checked_out"
    }).eq("id", shift_id).execute()
    # 2026-08-13 打刻済ルール移行: 退勤が入った瞬間にその日が支払い対象になるため常に再計算
    if row:
        _revert_payment_if_amount_affected(row[0], reason=f"退勤実績 {actual_end} 記録（要再計算）")


def bulk_checkout(shift_ids, actual_end, event_id=None):
    """一括退勤（凍結対応）。対象スタッフIDをリストで返す。"""
    client = core.get_client()
    affected_staff_ids = []
    for sid in shift_ids:
        row = client.table("p1_shifts").select(
            "planned_start, actual_start, staff_id, event_id"
        ).eq("id", sid).execute().data
        if not row:
            continue
        a_start = row[0].get("actual_start") or row[0].get("planned_start")
        affected_staff_ids.append(row[0].get("staff_id"))
        client.table("p1_shifts").update({
            "actual_end": actual_end, "actual_start": a_start, "status": "checked_out"
        }).eq("id", sid).execute()
        # 差し戻しだけ即時に行い、再計算は最後にまとめて（2026-08-14 バッチ化）
        try:
            _ev = row[0].get("event_id") or event_id
            if _ev:
                reset_payment_to_pending(_ev, row[0].get("staff_id"),
                                         reason=f"一括退勤 {actual_end} 記録（要再計算）")
        except Exception:
            pass
    # 2026-08-13 打刻済ルール移行: 一括退勤も金額を追随させる（文脈共有のバッチ再計算）
    try:
        _ev = event_id or (row[0].get("event_id") if row else None)
        if _ev and affected_staff_ids:
            from utils.payment_recalc import recalc_staff_payments
            recalc_staff_payments(_ev, affected_staff_ids)
    except Exception:
        pass
    if event_id:
        core.log_action("bulk_checkout", "shifts",
                    detail=f"{len(shift_ids)}名を{actual_end}で一括退勤",
                    event_id=event_id)
    return list({s for s in affected_staff_ids if s is not None})


# ============================================================
# 弁当配布チェック（2026-06-18 追加）
# ============================================================
# 大会期間中の弁当配布を「シフト1人1日」単位で管理する。
# マイグレ docs/db_migrations/20260618_add_lunch_status.sql 必須。
# 列が無い古いDBでも壊れないよう、UPDATE は失敗時に静かに無視する。
LUNCH_STATUSES = ("pending", "received", "cancelled")


def _validate_lunch_status(status: str) -> str:
    """状態文字列のバリデーション（不正値は例外）。

    'received'：配布済 ／ 'cancelled'：辞退 ／ 'pending'：未受領（既定）
    """
    s = (status or "").strip().lower()
    if s not in LUNCH_STATUSES:
        raise ValueError(f"lunch_status は {LUNCH_STATUSES} のいずれか（指定: {status!r}）")
    return s


def update_lunch_status(shift_id, status: str, performed_by: str = "") -> bool:
    """1つのシフトの弁当配布状態を更新。

    Returns: True=更新成功（or 既に同状態）、False=列未追加・対象なし等で失敗
    """
    s = _validate_lunch_status(status)
    try:
        core.get_client().table("p1_shifts").update({
            "lunch_status": s,
            "lunch_status_at": core._now(),
            "lunch_status_by": (performed_by or "")[:40],
        }).eq("id", shift_id).execute()
        return True
    except Exception:
        # 列が無い古いDB等：マイグレ未実行を呼び出し側で検知できるよう False を返す
        return False


def bulk_set_lunch_status(event_id, date, status: str, performed_by: str = "") -> int:
    """指定イベント×日付の出勤予定者全員に同じ状態を設定。

    欠勤者（status='absent'）は対象外。
    Returns: 更新対象だったシフト数（実反映件数。失敗時は 0）。
    """
    s = _validate_lunch_status(status)
    client = core.get_client()
    try:
        rows = client.table("p1_shifts").select("id").eq(
            "event_id", event_id).eq("date", date).neq("status", "absent").execute().data or []
        for r in rows:
            client.table("p1_shifts").update({
                "lunch_status": s,
                "lunch_status_at": core._now(),
                "lunch_status_by": (performed_by or "")[:40],
            }).eq("id", r["id"]).execute()
        core.log_action("bulk_set_lunch_status", "shifts",
                   detail=f"{date} の {len(rows)}名を {s} に設定",
                   event_id=event_id, performed_by=(performed_by or "system"))
        return len(rows)
    except Exception:
        return 0


def get_lunch_summary(event_id, date) -> dict:
    """指定イベント×日付の弁当配布サマリ。

    Returns: {"received": N, "pending": N, "cancelled": N, "total_active": N}
       total_active = 出勤予定者数（欠勤除外）。
    """
    client = core.get_client()
    try:
        rows = client.table("p1_shifts").select(
            "lunch_status, status"
        ).eq("event_id", event_id).eq("date", date).execute().data or []
    except Exception:
        return {"received": 0, "pending": 0, "cancelled": 0, "total_active": 0}
    out = {"received": 0, "pending": 0, "cancelled": 0, "total_active": 0}
    for r in rows:
        if (r.get("status") or "") == "absent":
            continue
        out["total_active"] += 1
        ls = (r.get("lunch_status") or "pending").lower()
        if ls in out:
            out[ls] += 1
    return out


# ============================================================
# 配布チェック汎用（弁当2個目・ドリンクチケット 2026-07-02 追加）
# ============================================================
# lunch  : 弁当1個目（20260618 既存列 lunch_status）
# lunch2 : 弁当2個目。12時間以上の予定シフト者のみUIに表示
# drink  : ドリンクチケット（一律2枚＝配布済みかの1チェック）
# マイグレ docs/db_migrations/20260702_add_lunch2_drink_status.sql 必須。
# 列が無い古いDBでも壊れないよう、失敗は False / 0 で返す（lunch関数と同じ流儀）。
DISTRIBUTION_KINDS = {
    "lunch": "lunch_status",
    "lunch2": "lunch2_status",
    "drink": "drink_status",
}

# 弁当2個目の対象となる予定シフト時間（分）
LUNCH2_THRESHOLD_MINUTES = 12 * 60


def planned_shift_minutes(planned_start, planned_end) -> int:
    """予定シフトの拘束時間（分）。'26:00' 等の24時超え表記に対応。不正値は0。"""
    try:
        h1, m1 = map(int, str(planned_start).strip().split(":"))
        h2, m2 = map(int, str(planned_end).strip().split(":"))
        return max(0, (h2 * 60 + m2) - (h1 * 60 + m1))
    except (ValueError, AttributeError):
        return 0


def _distribution_column(kind: str) -> str:
    col = DISTRIBUTION_KINDS.get((kind or "").strip().lower())
    if not col:
        raise ValueError(f"kind は {tuple(DISTRIBUTION_KINDS)} のいずれか（指定: {kind!r}）")
    return col


def update_distribution_status(shift_id, kind: str, status: str, performed_by: str = "") -> bool:
    """1つのシフトの配布状態（弁当2個目/ドリンク等）を更新。

    Returns: True=更新成功、False=列未追加（マイグレ未実行）等で失敗
    """
    col = _distribution_column(kind)
    s = _validate_lunch_status(status)
    try:
        core.get_client().table("p1_shifts").update({
            col: s,
            f"{col}_at": core._now(),
            f"{col}_by": (performed_by or "")[:40],
        }).eq("id", shift_id).execute()
        return True
    except Exception:
        return False


def bulk_set_distribution_status(event_id, date, kind: str, status: str,
                                 performed_by: str = "") -> int:
    """指定イベント×日付の出勤予定者全員に同じ配布状態を設定（欠勤者除外）。

    Returns: 実反映件数（失敗時は 0）。
    """
    col = _distribution_column(kind)
    s = _validate_lunch_status(status)
    client = core.get_client()
    try:
        rows = client.table("p1_shifts").select("id").eq(
            "event_id", event_id).eq("date", date).neq("status", "absent").execute().data or []
        for r in rows:
            client.table("p1_shifts").update({
                col: s,
                f"{col}_at": core._now(),
                f"{col}_by": (performed_by or "")[:40],
            }).eq("id", r["id"]).execute()
        core.log_action(f"bulk_set_{kind}_status", "shifts",
                   detail=f"{date} の {len(rows)}名を {s} に設定",
                   event_id=event_id, performed_by=(performed_by or "system"))
        return len(rows)
    except Exception:
        return 0


def get_handout_summary(event_id, date) -> dict:
    """指定イベント×日付の配布サマリ（弁当1・弁当2・ドリンクをまとめて1クエリで）。

    Returns:
        {"lunch": {...}, "lunch2": {...}, "drink": {...},
         "total_active": N, "migrated": bool}
        migrated=False は lunch2/drink 列が未追加（マイグレ未実行）。
        その場合 lunch2/drink はゼロ埋め・lunch のみ有効。
    """
    client = core.get_client()
    empty = {"received": 0, "pending": 0, "cancelled": 0}
    out = {"lunch": dict(empty), "lunch2": dict(empty), "drink": dict(empty),
           "total_active": 0, "migrated": True}
    try:
        rows = client.table("p1_shifts").select(
            "status, lunch_status, lunch2_status, drink_status"
        ).eq("event_id", event_id).eq("date", date).execute().data or []
    except Exception:
        out["migrated"] = False
        lunch_only = get_lunch_summary(event_id, date)
        out["total_active"] = lunch_only.pop("total_active", 0)
        out["lunch"] = lunch_only
        return out
    for r in rows:
        if (r.get("status") or "") == "absent":
            continue
        out["total_active"] += 1
        for kind, col in DISTRIBUTION_KINDS.items():
            v = (r.get(col) or "pending").lower()
            if v in out[kind]:
                out[kind][v] += 1
    return out


def mark_absent(shift_id):
    client = core.get_client()
    row = client.table("p1_shifts").select("event_id, staff_id").eq("id", shift_id).execute().data
    client.table("p1_shifts").update({
        "status": "absent", "actual_start": None, "actual_end": None
    }).eq("id", shift_id).execute()
    # 欠勤はその日の支払いが丸ごと変わるため、計算済みの支払いを未承認に差し戻す
    if row:
        _revert_payment_if_amount_affected(row[0], reason="欠勤記録（要再計算）")


def set_shift_mix(shift_id, is_mix):
    core.get_client().table("p1_shifts").update({"is_mix": is_mix}).eq("id", shift_id).execute()
