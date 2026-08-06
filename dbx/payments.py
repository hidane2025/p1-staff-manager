"""支払い・承認・個別手当・小口（db.py から2026-08-06に機械分割・挙動不変）"""
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


def reset_payment_to_pending(event_id, staff_id, reason="凍結再計算"):
    """支払いを未承認に戻す（凍結発生時の再計算準備）。

    支払済み(paid)は保護。承認済み(approved)→未承認(pending)に戻す。
    Returns: True=リセット成功、False=支払済みで保護 or レコードなし
    """
    client = core.get_client()
    existing = client.table("p1_payments").select("id, status").eq(
        "event_id", event_id).eq("staff_id", staff_id).execute().data
    if not existing:
        return False
    payment = existing[0]
    if payment["status"] == "paid":
        core.log_action("freeze_recalc_skipped", "payments", payment["id"],
                    detail=f"{reason}: 支払済みのため保護", event_id=event_id)
        return False
    # 2026-07-29 修正: 状態を確認してから更新するまでの間に他端末が支払済みにすると、
    # 支払済みが未承認へ巻き戻る競合があった（ピット端末と給与窓口の同時操作で起こりうる）。
    # 更新条件に status を含め、DB側で原子的に弾く。
    _res = client.table("p1_payments").update({
        "status": "pending", "approved_by": None, "approved_at": None,
    }).eq("id", payment["id"]).neq("status", "paid").execute()
    if not _res.data:
        core.log_action("freeze_recalc_skipped", "payments", payment["id"],
                   detail=f"{reason}: 直前に支払済みへ変化したため保護", event_id=event_id)
        return False
    core.log_action("freeze_recalc", "payments", payment["id"],
                detail=f"{reason}: 未承認に戻した", event_id=event_id)
    return True


# === Payments ===

def rounding_supported() -> bool:
    """端数処理(payable_amount/rounding_unit)のマイグレが適用済みか。

    未適用だと rounding_unit を保存できず payable_amount も計算できないため、
    UI 側で端数処理セレクタを無効化する判定に使う（無限リランの防止）。
    """
    from utils import db_schema
    return (db_schema.has_column("p1_events", "rounding_unit")
            and db_schema.has_column("p1_payments", "payable_amount"))


def get_event_rounding_unit(event_id) -> int:
    """イベントの端数処理単位（0=なし/100/500/1000）を返す。

    A-6 (2026-06-01): payable_amount 算出に使う。rounding_unit 列が未適用の環境では 0。
    """
    from utils import db_schema
    if not db_schema.has_column("p1_events", "rounding_unit"):
        return 0
    row = core.get_client().table("p1_events").select("rounding_unit").eq(
        "id", event_id).execute().data
    try:
        return int(row[0].get("rounding_unit") or 0) if row else 0
    except (TypeError, ValueError):
        return 0


def compute_payable_amount(total_amount: int, rounding_unit: int) -> int:
    """支払確定額（丸め後）を返す。rounding_unit=0 なら total そのまま（ゼロ除算回避）。"""
    from utils.denomination import round_amount
    ru = int(rounding_unit or 0)
    if ru <= 0:
        return int(total_amount)
    return round_amount(int(total_amount), ru)


def get_payable(payment: dict) -> int:
    """支払レコードから「実際に支払う確定額」を取り出す（A-6 の唯一の正）。

    payable_amount 列があればそれを、無い/NULL の旧行は total_amount を代替値とする。
    封筒・領収書・年間累計・精算レポート・ピット端末はすべてこの関数を通して金額を表示する。
    """
    if payment is None:
        return 0
    val = payment.get("payable_amount")
    if val is None:
        val = payment.get("total_amount", 0)
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def save_payment(event_id, staff_id, base_pay, night_pay, transport_total,
                 floor_bonus_total, mix_bonus_total, attendance_bonus,
                 total_amount, break_deduction=0, adjustment=0, adjustment_note="",
                 individual_allowance_total: int = 0):
    """支払いレコードを保存（既存の pending/approved は削除して上書き、paid は保護）

    Codex P2 fix #3 (2026-05-09): individual_allowance_total を追加
    （個別手当の合計を保存して、内訳と合計の整合性を確保）
    A-5/A-6 (2026-06-01):
      - total_amount は adjustment（臨時調整）込みで渡される前提（calculator が含める）。
      - payable_amount = round(total_amount, event.rounding_unit) を算出して保存し、
        封筒・領収書・年間累計が同じ確定額を参照できるようにする。
      - 再計算で手入力メモ(notes)が消えないよう、既存 notes を読み出して引き継ぐ。
    マイグレ未実行時は db_schema.has_column チェックでスキップする後方互換あり。
    """
    from utils import db_schema
    client = core.get_client()
    # notes 列はマイグレ未適用の環境では存在しないため、SELECT も条件付きで組む
    # （無条件に notes を select すると古いDBで save_payment 自体が失敗する）。
    _has_notes = db_schema.has_column("p1_payments", "notes")
    _sel = "id, status, notes" if _has_notes else "id, status"
    existing = client.table("p1_payments").select(_sel).eq(
        "event_id", event_id).eq("staff_id", staff_id).execute()
    existing_notes = ""
    if existing.data:
        if existing.data[0]["status"] == "paid":
            return  # 支払済みは上書きしない
        # A-5: 再計算で消えないよう手入力メモを退避
        existing_notes = existing.data[0].get("notes") or "" if _has_notes else ""
    payload = {
        "event_id": event_id, "staff_id": staff_id,
        "base_pay": base_pay, "night_pay": night_pay, "transport_total": transport_total,
        "floor_bonus_total": floor_bonus_total, "mix_bonus_total": mix_bonus_total,
        "attendance_bonus": attendance_bonus, "break_deduction": break_deduction,
        "adjustment": adjustment, "adjustment_note": adjustment_note,
        "total_amount": total_amount,
    }
    # A-5: 手入力メモを引き継ぐ（notes 列がある場合のみ）
    if existing_notes and db_schema.has_column("p1_payments", "notes"):
        payload["notes"] = existing_notes
    if individual_allowance_total and db_schema.has_column(
        "p1_payments", "individual_allowance_total"
    ):
        payload["individual_allowance_total"] = int(individual_allowance_total)
    # A-6: 支払確定額（丸め後）を保存
    if db_schema.has_column("p1_payments", "payable_amount"):
        payload["payable_amount"] = compute_payable_amount(
            total_amount, get_event_rounding_unit(event_id)
        )
    # 2026-07-29 修正: 以前は「既存を削除してから挿入」していたため、削除に成功して
    # 挿入で通信が切れると支払いレコードが丸ごと消えた（会場Wi-Fi断で現実に起こりうる）。
    # 既存があれば更新、無ければ挿入に変更し、データが消える瞬間を無くした。
    # 更新には status 述語を付け、確認から更新までの間に他端末が支払済みにした場合も弾く。
    if existing.data:
        # 2026-08-02: 金額が変わるのに承認・領収書がそのまま残る欠陥を是正。
        # ピット端末の再打刻（多日程スタッフは毎日通る）で
        #   ・誰も承認していない金額が「承認済み」として現金支払いされる
        #   ・旧額の領収書PDFとトークンが有効なまま、違う額の現金が渡る
        # という統制の穴があった。set_payment_adjustment / recompute_payable_for_event は
        # 既に同じ状況で差し戻し・失効を行っており、save_payment だけが漏れていた。
        _old_total = int(existing.data[0].get("total_amount") or 0)
        if int(total_amount or 0) != _old_total:
            # 金額が変わった → 承認をやり直させる（承認情報もクリア）
            payload["status"] = "pending"
            payload["approved_by"] = None
            payload["approved_at"] = None
            # 旧額の領収書は無効化する（再発行が必要）
            if db_schema.has_column("p1_payments", "receipt_received"):
                payload["receipt_received"] = 0
            if db_schema.has_column("p1_payments", "receipt_pdf_path"):
                payload["receipt_pdf_path"] = None
                payload["receipt_token"] = None
                if db_schema.has_column("p1_payments", "receipt_token_expires_at"):
                    payload["receipt_token_expires_at"] = None
            core.log_action("payment_reverted_by_recalc", "payments", staff_id,
                       f"再計算で金額変更（¥{_old_total:,}→¥{total_amount:,}）のため"
                       "未承認へ差し戻し・領収書を無効化", event_id)
        _res = client.table("p1_payments").update(payload).eq(
            "id", existing.data[0]["id"]).neq("status", "paid").execute()
        if not _res.data:
            # 直前に支払済みへ変わった等で更新されなかった場合は何も壊さず終了
            core.log_action("calculate_payment_skipped", "payments", staff_id,
                       "支払済みへ変化したため上書きせず", event_id)
            return
    else:
        client.table("p1_payments").insert(payload).execute()
    core.log_action("calculate_payment", "payments", staff_id, f"合計¥{total_amount:,}", event_id)


def set_payment_adjustment(payment_id, adjustment, adjustment_note="",
                            event_id=None, performed_by="system"):
    """既存支払いの臨時調整額(adjustment)だけを更新する（A-5 の編集UI用）。

    シフトからの再計算をせず、total_amount/payable_amount を整合させて差し替える:
        components = 旧 total_amount - 旧 adjustment
        新 total   = components + 新 adjustment
    paid は保護（変更不可）。Returns: True=更新成功 / False=支払済み or レコードなし。
    """
    from utils import db_schema
    client = core.get_client()
    row = client.table("p1_payments").select(
        "status, total_amount, adjustment").eq("id", payment_id).execute().data
    if not row:
        return False
    # 臨時調整の編集は未承認(pending)のみ許可（UIと一致）。承認/支払済みは再承認を
    # 経るべきなので、ここでブロックする。並走で承認/支払されても下の status 述語で原子的に弾く。
    if row[0].get("status") != "pending":
        return False
    old_total = int(row[0].get("total_amount") or 0)
    old_adj = int(row[0].get("adjustment") or 0)
    try:
        new_adj = int(adjustment or 0)
    except (TypeError, ValueError):
        new_adj = 0
    new_total = (old_total - old_adj) + new_adj
    payload = {
        "adjustment": new_adj,
        "adjustment_note": adjustment_note or "",
        "total_amount": new_total,
    }
    if db_schema.has_column("p1_payments", "payable_amount"):
        payload["payable_amount"] = compute_payable_amount(
            new_total, get_event_rounding_unit(event_id) if event_id else 0
        )
    # A-6: 金額が変わったら、既発行の領収書（PDF/トークン）と受領フラグを無効化する。
    # 旧額の領収書が再利用される・旧額のまま支払われるのを防ぐ（要再発行）。
    if new_total != old_total:
        if db_schema.has_column("p1_payments", "receipt_received"):
            payload["receipt_received"] = 0
        if db_schema.has_column("p1_payments", "receipt_pdf_path"):
            payload["receipt_pdf_path"] = None
            payload["receipt_token"] = None
            if db_schema.has_column("p1_payments", "receipt_token_expires_at"):
                payload["receipt_token_expires_at"] = None
    # TOCTOU 対策: フォーム表示中に他セッションが承認/支払した場合に備え、
    # status=pending を述語に含めて原子的に更新する。0件なら変更が起きなかったとして False。
    res = client.table("p1_payments").update(payload).eq(
        "id", payment_id).eq("status", "pending").execute()
    if not res.data:
        return False
    core.log_action("set_adjustment", "payments", payment_id,
               f"臨時調整 ¥{new_adj:,}（{adjustment_note or '—'}）→ 合計¥{new_total:,}"
               + ("／領収書無効化" if new_total != old_total else ""),
               event_id, performed_by=performed_by)
    return True


def recompute_payable_for_event(event_id, rounding_unit=None):
    """イベント内の未払い(pending/approved)支払いの payable_amount を再計算する（A-6）。

    端数処理単位を変えたとき、全件のシフト再計算をせず、保存済み total_amount を
    新しい単位で丸め直すだけで封筒・領収書・年間累計を整合させる。
    paid は確定済みのため触らない。Returns: 更新した件数。
    """
    from utils import db_schema
    if not db_schema.has_column("p1_payments", "payable_amount"):
        return 0
    ru = get_event_rounding_unit(event_id) if rounding_unit is None else int(rounding_unit or 0)
    client = core.get_client()
    # receipt 列があれば、確定額が変わった行の旧領収書を無効化するため一緒に取得
    _has_receipt = db_schema.has_column("p1_payments", "receipt_pdf_path")
    cols = "id, total_amount, payable_amount, status"
    if _has_receipt:
        cols += ", receipt_pdf_path, receipt_token"
    rows = client.table("p1_payments").select(cols).eq("event_id", event_id).execute().data
    n = 0
    invalidated = 0
    reverted = 0
    for r in rows:
        if r.get("status") == "paid":
            continue
        new_payable = compute_payable_amount(r.get("total_amount") or 0, ru)
        update = {"payable_amount": new_payable}
        # A-6: 確定額が変わったのに旧領収書PDF/トークン/受領フラグが残っていると、
        # PDFの額面・支払い可否ゲートが旧額のままになる。発行済みなら無効化して再発行を促す。
        changed = int(r.get("payable_amount") or r.get("total_amount") or 0) != int(new_payable)
        _did_invalidate = False
        _did_revert = False
        if changed:
            # 受領フラグは旧額に対するものなのでリセット（支払いゲートを再確認させる）
            if db_schema.has_column("p1_payments", "receipt_received"):
                update["receipt_received"] = 0
            if _has_receipt and (r.get("receipt_pdf_path") or r.get("receipt_token")):
                update["receipt_pdf_path"] = None
                update["receipt_token"] = None
                if db_schema.has_column("p1_payments", "receipt_token_expires_at"):
                    update["receipt_token_expires_at"] = None
                _did_invalidate = True
            # 内部統制: 承認済みの金額が変わったら再承認を必須化（未承認へ差し戻し）。
            # 通常の再計算が approved を保護するのと整合させ、無承認での金額変更を防ぐ。
            if r.get("status") == "approved":
                update["status"] = "pending"
                update["approved_by"] = None
                update["approved_at"] = None
                _did_revert = True
        # TOCTOU 対策: select 後に他セッションが status を変えた（特に paid 化）場合に
        # 上書き・差し戻ししないよう、観測した status を述語に含めて原子的に更新する。
        res = client.table("p1_payments").update(update).eq(
            "id", r["id"]).eq("status", r.get("status")).execute()
        if res.data:
            n += 1
            # 実際に書き込めた行だけカウント（並走で弾かれた行は数えない）
            if _did_invalidate:
                invalidated += 1
            if _did_revert:
                reverted += 1
    if invalidated or reverted:
        core.log_action(
            "invalidate_receipts_rounding", "payments", None,
            detail=(f"端数処理変更: 領収書無効化 {invalidated} 件 / "
                    f"承認差し戻し {reverted} 件（要再承認・再発行）"),
            event_id=event_id,
        )
    return {"updated": n, "invalidated": invalidated, "reverted": reverted}


def get_payments_for_event(event_id):
    data = core.get_client().table("p1_payments").select("*, p1_staff(name_jp, name_en, no, role)").eq("event_id", event_id).order("staff_id").execute().data
    return _flatten_staff_join(data)


def get_yearly_totals(year, staff_id=None):
    """指定年(1/1〜12/31)の全スタッフ累計支払額を取得

    Returns: [{staff_id, name_jp, no, role, employment_type,
              total_amount, event_count, event_names}]
    """
    client = core.get_client()
    # その年のイベント一覧
    events = client.table("p1_events").select("id, name").gte(
        "start_date", f"{year}-01-01").lte("start_date", f"{year}-12-31").execute().data
    event_ids = [e["id"] for e in events]
    event_name_map = {e["id"]: e["name"] for e in events}
    if not event_ids:
        return []

    # 支払いを取得
    q = client.table("p1_payments").select("*").in_("event_id", event_ids)
    if staff_id:
        q = q.eq("staff_id", staff_id)
    payments = q.execute().data

    # スタッフ情報を別途取得（結合のdict/list不確定問題を回避）
    staff_ids = list({p["staff_id"] for p in payments})
    if not staff_ids:
        return []
    staff_data = client.table("p1_staff").select(
        "id, name_jp, name_en, no, role, employment_type, real_name, email, address"
    ).in_("id", staff_ids).execute().data
    staff_map = {s["id"]: s for s in staff_data}

    # スタッフごとに集計
    totals = {}
    for p in payments:
        s_id = p["staff_id"]
        staff_info = staff_map.get(s_id, {})
        if s_id not in totals:
            totals[s_id] = {
                "staff_id": s_id,
                "name_jp": staff_info.get("name_jp", ""),
                "name_en": staff_info.get("name_en", ""),
                "no": staff_info.get("no", 0),
                "role": staff_info.get("role", "Dealer"),
                "employment_type": staff_info.get("employment_type", "contractor"),
                "real_name": staff_info.get("real_name") or "",
                "email": staff_info.get("email") or "",
                "address": staff_info.get("address") or "",
                "total_amount": 0,
                "paid_amount": 0,
                "event_count": 0,
                "event_names": set(),
            }
        # A-6: 年間累計も支払確定額(payable_amount)で集計し、封筒/領収書と一致させる。
        _amt = get_payable(p)
        totals[s_id]["total_amount"] += _amt
        if p.get("status") == "paid":
            totals[s_id]["paid_amount"] += _amt
        totals[s_id]["event_count"] += 1
        totals[s_id]["event_names"].add(event_name_map.get(p["event_id"], ""))

    # setをlistに変換
    result = []
    for v in totals.values():
        v["event_names"] = sorted(v["event_names"])
        result.append(v)
    return sorted(result, key=lambda x: -x["total_amount"])


def approve_payment(payment_id, approved_by, event_id=None):
    """pending → approved のみ許可（状態遷移ガード）。

    A-3/A-9 (2026-06-01): `.eq("status","pending")` を付与し、
    承認スキップ（pending以外をいきなり承認）・並走競合・逆行を防ぐ。
    Returns: True=承認できた / False=pending以外（既に承認/支払済 or 競合）で変化なし。
    """
    res = core.get_client().table("p1_payments").update({
        "status": "approved", "approved_by": approved_by, "approved_at": core._now()
    }).eq("id", payment_id).eq("status", "pending").execute()
    changed = bool(res.data)
    if changed:
        core.log_action("approve_payment", "payments", payment_id,
                   f"承認者: {approved_by}", event_id, performed_by=approved_by)
    else:
        core.log_action("approve_payment_noop", "payments", payment_id,
                   "pending以外のため承認スキップ（状態不一致/競合）",
                   event_id, performed_by=approved_by)
    return changed


def mark_paid(payment_id, event_id=None, performed_by="system"):
    """approved → paid のみ許可（状態遷移ガード）＋支払実行者を記録。

    A-2 (2026-06-01): performed_by を監査ログと paid_by 列（has_column 後方互換）に記録。
        現金確定という最も不可逆な操作の実行者を追跡可能にする。
    A-3/A-9: `.eq("status","approved")` を付与し、承認スキップ・paid二重化・
        並走競合（TOCTOU）を DB 条件側でブロックする。
    Returns: True=支払済にできた / False=approved以外（既に支払済 or 競合）で変化なし。
    """
    from utils import db_schema
    payload = {"status": "paid", "paid_at": core._now()}
    if performed_by and db_schema.has_column("p1_payments", "paid_by"):
        payload["paid_by"] = str(performed_by)
    res = core.get_client().table("p1_payments").update(payload).eq(
        "id", payment_id).eq("status", "approved").execute()
    changed = bool(res.data)
    if changed:
        core.log_action("mark_paid", "payments", payment_id,
                   f"支払実行: {performed_by}", event_id, performed_by=performed_by)
    else:
        core.log_action("mark_paid_noop", "payments", payment_id,
                   "approved以外のため支払スキップ（状態不一致/競合）",
                   event_id, performed_by=performed_by)
    return changed


def mark_receipt_received(payment_id, event_id=None, performed_by="system"):
    """領収書受領フラグを立てる。A-2: 実行者を監査ログに記録。"""
    core.get_client().table("p1_payments").update({"receipt_received": 1}).eq("id", payment_id).execute()
    core.log_action("receipt_received", "payments", payment_id, "", event_id, performed_by=performed_by)


# === Individual Allowances (Phase 3-I, 2026-05-08) ===

def get_individual_allowances(event_id: int, staff_id: Optional[int] = None) -> list:
    """個別手当を取得

    Args:
        event_id: 対象イベント
        staff_id: 指定すればそのスタッフのみ。Noneなら全員分

    Returns:
        [{id, event_id, staff_id, allowance_type, label, amount,
          is_off_record, note, created_at, created_by}, ...]

    マイグレ未実行時は空リストを返す（後方互換）。
    """
    from utils import db_schema
    if not db_schema.has_column("p1_staff_event_allowances", "id"):
        return []
    q = core.get_client().table("p1_staff_event_allowances").select(
        "*").eq("event_id", event_id)
    if staff_id is not None:
        q = q.eq("staff_id", staff_id)
    return q.execute().data or []


def add_individual_allowance(event_id: int, staff_id: int,
                              allowance_type: str, amount: int,
                              label: str = "", is_off_record: int = 0,
                              note: str = "", created_by: str = "system") -> Optional[int]:
    """個別手当を1件追加

    Args:
        allowance_type: "language" / "recruitment" / "leadership" / "other"
        amount: 円単位
        is_off_record: 1 なら ピット端末で内訳非表示
    Returns:
        作成された ID（マイグレ未実行時は None）
    """
    from utils import db_schema
    if not db_schema.has_column("p1_staff_event_allowances", "id"):
        return None
    r = core.get_client().table("p1_staff_event_allowances").insert({
        "event_id": event_id, "staff_id": staff_id,
        "allowance_type": allowance_type,
        "label": label or _allowance_default_label(allowance_type),
        "amount": int(amount),
        "is_off_record": int(is_off_record),
        "note": note,
        "created_by": created_by,
    }).execute()
    aid = r.data[0]["id"] if r.data else None
    if aid:
        core.log_action(
            "add_individual_allowance", "allowances", aid,
            detail=f"{allowance_type} ¥{amount:,}"
            + (" (オフレコ)" if is_off_record else ""),
            event_id=event_id, performed_by=created_by,
        )
    return aid


def remove_individual_allowance(allowance_id: int, event_id: Optional[int] = None,
                                 performed_by: str = "system") -> bool:
    """個別手当を1件削除"""
    from utils import db_schema
    if not db_schema.has_column("p1_staff_event_allowances", "id"):
        return False
    core.get_client().table("p1_staff_event_allowances").delete().eq(
        "id", allowance_id).execute()
    core.log_action(
        "remove_individual_allowance", "allowances", allowance_id,
        detail="削除", event_id=event_id, performed_by=performed_by,
    )
    return True


def _allowance_default_label(allowance_type: str) -> str:
    """allowance_type からデフォルトラベル"""
    return {
        "language": "言語手当",
        "recruitment": "人材確保手当",
        "leadership": "リーダー手当",
        "other": "個別手当",
    }.get(allowance_type, "個別手当")


# === Petty Cash ===

def add_petty_cash(event_id, date, description, amount, requester, approver="",
                   account_code: str = "", payee_name: str = ""):
    """小口経費を追加

    v3.8 (2026-05-08) で account_code（勘定科目）と payee_name（領収書宛名）を追加。
    マイグレーション 20260508_add_petty_cash_accounting.sql 未実行時は無視される
    （後方互換）。
    """
    from utils import db_schema
    payload = {
        "event_id": event_id, "date": date, "description": description,
        "amount": amount, "requester": requester, "approver": approver,
    }
    # 後方互換: マイグレ後のカラムは存在チェックして条件付きで投入
    if account_code and db_schema.has_column("p1_petty_cash", "account_code"):
        payload["account_code"] = account_code
    if payee_name and db_schema.has_column("p1_petty_cash", "payee_name"):
        payload["payee_name"] = payee_name
    core.get_client().table("p1_petty_cash").insert(payload).execute()
    core.log_action(
        "add_petty_cash", "petty_cash",
        detail=f"¥{amount:,} {description}"
        + (f" [{account_code}]" if account_code else ""),
        event_id=event_id,
    )


def get_petty_cash_for_event(event_id):
    return core.get_client().table("p1_petty_cash").select("*").eq("event_id", event_id).order("date").order("created_at").execute().data
