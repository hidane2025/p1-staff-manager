"""大会後の作業終了状態をセットアップ

中野さんが Streamlit Cloud で全機能を触れるように、
80名規模の架空大会を『大会終了後・一部支払完了・一部領収書発行済み』の状態にする。

※cleanupしない。データは残留する。再実行すると上書き（同名イベント削除→再作成）。
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db  # type: ignore
from utils import calculator, shift_parser, receipt_db, receipt_issuer

TEST_DIR = Path(__file__).resolve().parent
STAFF_CSV = TEST_DIR / "01_staff_master.csv"
SHIFT_CSV = TEST_DIR / "02_shift_kyoto.csv"
EVENT_JSON = TEST_DIR / "03_event_config.json"


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def cleanup_existing(event_name: str) -> None:
    """同名イベントのみ削除"""
    client = db.get_client()
    events = client.table("p1_events").select("id").eq("name", event_name).execute().data
    for e in events:
        eid = e["id"]
        pays = client.table("p1_payments").select("receipt_pdf_path").eq("event_id", eid).execute().data
        # Storage上のPDFも削除
        from utils import receipt_storage
        for p in pays:
            if p.get("receipt_pdf_path"):
                try:
                    receipt_storage.delete_pdf(p["receipt_pdf_path"])
                except Exception:
                    pass
        for tbl in ["p1_payments", "p1_shifts", "p1_event_rates",
                    "p1_event_transport_rules", "p1_transport_claims",
                    "p1_petty_cash", "p1_audit_log"]:
            try:
                client.table(tbl).delete().eq("event_id", eid).execute()
            except Exception:
                pass
        client.table("p1_events").delete().eq("id", eid).execute()


def main() -> int:
    # 1. 既存テストデータ削除
    section("Step 0: 既存同名イベント掃除")
    cfg = json.loads(EVENT_JSON.read_text(encoding="utf-8"))
    cleanup_existing(cfg["name"])
    print("  ✅ クリーン")

    # 2. スタッフ一括登録
    section("Step 1: スタッフ一括登録")
    rows = []
    with STAFF_CSV.open("r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    res = db.bulk_import_staff(rows)
    print(f"  新規 {res['created']} / 更新 {res['updated']} / エラー {len(res['errors'])}")

    client = db.get_client()
    staff_all = client.table("p1_staff").select(
        "id, no, name_jp, employment_type, custom_hourly_rate"
    ).gte("no", 100).lte("no", 199).execute().data
    name_to_id = {s["name_jp"]: s["id"] for s in staff_all}
    print(f"  ✅ スタッフ {len(staff_all)}名 稼働中")

    # 3. イベント作成＋レート
    section("Step 2: イベント作成＋レート設定")
    event_id = db.create_event(
        cfg["name"], cfg["venue"], cfg["start_date"], cfg["end_date"],
        break_minutes_6h=45, break_minutes_8h=60,
    )
    for date, r in cfg["rates"].items():
        db.set_event_rate(event_id, date, r["hourly"], r["night"], r["transport"],
                           r["floor_bonus"], r["mix_bonus"], r["date_label"])
    print(f"  ✅ イベント id={event_id}")

    # 4. 発行者情報
    receipt_db.save_issuer_settings(
        event_id,
        issuer_name="株式会社パシフィック",
        issuer_address="東京都港区XX X-X-X",
        issuer_tel="03-0000-0000",
        invoice_number="",
        receipt_purpose="ポーカー大会運営業務委託費として",
    )
    print("  ✅ 発行者情報セット（インボイス未登録で運用）")

    # 5. シフト取込
    section("Step 3: シフト取込")
    parsed = shift_parser.parse_shift_csv(SHIFT_CSV.read_bytes(), year=2026)
    imported = 0
    for srow in parsed.get("shifts", []):
        sid = name_to_id.get(srow["name_jp"])
        if not sid:
            continue
        pt = calculator.parse_shift_time(srow.get("time_range") or "")
        if not pt:
            continue
        sm, em = pt
        db.upsert_shift(
            event_id, sid, srow["date"],
            f"{sm // 60:02d}:{sm % 60:02d}",
            f"{em // 60:02d}:{em % 60:02d}",
            is_mix=0,
        )
        imported += 1
    print(f"  ✅ {imported}件取込")

    # 6. 交通費ルール
    section("Step 4: 交通費ルール")
    db.save_transport_rules(event_id, cfg["transport_rules"])
    print(f"  ✅ {len(cfg['transport_rules'])}地域")

    # 7. 出退勤：欠勤・遅刻・最終日凍結退勤
    section("Step 5: 出退勤（欠勤3・遅刻2・最終日凍結退勤20名）")
    shifts = db.get_shifts_for_event(event_id)
    # 欠勤3件
    for s in shifts[:3]:
        db.mark_absent(s["id"])
    # 遅刻2件（+30分）
    for s in shifts[3:5]:
        h, m = s["planned_start"].split(":")
        tot = int(h) * 60 + int(m) + 30
        db.checkin_staff(s["id"], f"{tot // 60:02d}:{tot % 60:02d}")
    # 最終日 (2026-08-17) の前半20名を26:00凍結退勤
    day5 = [s for s in shifts if s["date"] == "2026-08-17"][:20]
    if day5:
        db.bulk_checkout([s["id"] for s in day5], "26:00", event_id=event_id)
    print(f"  ✅ 出退勤記録完了")

    # 8. 交通費領収書入力（非開催地30名）
    section("Step 6: 交通費領収書入力（非開催地30名）")
    rules = {r["region"]: r for r in db.get_transport_rules(event_id)}
    non_kinki_staff = [s for s in staff_all if s.get("id")]
    # regionを取りに行く
    staff_regions = {r["id"]: r.get("region") for r in client.table("p1_staff").select("id, region").in_(
        "id", [s["id"] for s in staff_all]).execute().data}
    count = 0
    for s in staff_all:
        region = staff_regions.get(s["id"])
        if not region or region == "近畿":
            continue
        rule = rules.get(region)
        if not rule:
            continue
        sample = {"東海": 6000, "関東": 13500, "甲信越": 10500, "北陸": 8500,
                  "中国": 9000, "四国": 11000, "九州": 22000, "東北": 18000,
                  "北海道": 26000, "沖縄": 28000}.get(region, 8000)
        approved = min(sample, rule["max_amount"])
        db.upsert_transport_claim(event_id, s["id"], sample, approved, 1, "")
        count += 1
        if count >= 30:
            break
    print(f"  ✅ {count}件の領収書入力完了")

    # 9. 支払い計算（500円丸め）
    section("Step 7: 支払い計算（500円丸め）")
    rates = db.get_event_rates(event_id)
    rates_by_date = {r["date"]: {
        "hourly": r["hourly_rate"], "night": r["night_rate"],
        "transport": r["transport_allowance"],
        "floor_bonus": r["floor_bonus"], "mix_bonus": r["mix_bonus"],
    } for r in rates}
    shifts = db.get_shifts_for_event(event_id)
    by_staff: dict[int, list[dict]] = {}
    for s in shifts:
        if s.get("status") == "absent":
            continue
        by_staff.setdefault(s["staff_id"], []).append({
            "date": s["date"], "start": s["planned_start"],
            "end": s["planned_end"], "is_mix": bool(s.get("is_mix")),
        })
    claims = {c["staff_id"]: c for c in db.get_transport_claims(event_id)}
    staff_info = {s["id"]: s for s in client.table("p1_staff").select("*").in_(
        "id", list(by_staff.keys())).execute().data}

    total_amount_sum = 0
    for sid, sh in by_staff.items():
        info = staff_info.get(sid, {})
        emp = info.get("employment_type", "contractor")
        custom = info.get("custom_hourly_rate") if emp == "timee" else None
        transport_override = None
        if sid in claims:
            transport_override = claims[sid]["approved_amount"] * len(sh)
        pay = calculator.calculate_staff_payment(
            staff_id=sid, name=info.get("name_jp", ""),
            role=info.get("role", "Dealer"),
            shifts=sh, rates_by_date=rates_by_date,
            total_event_days=len(rates_by_date),
            employment_type=emp, custom_hourly_rate=custom,
            transport_override=transport_override,
        )
        total = pay.total_amount
        total = ((total + 499) // 500) * 500   # 500円丸め
        total_amount_sum += total
        db.save_payment(
            event_id, sid, pay.base_pay, pay.night_pay, pay.transport_total,
            pay.floor_bonus_total, pay.mix_bonus_total, pay.attendance_bonus,
            total, break_deduction=pay.break_deduction,
        )
    print(f"  ✅ 支払い計算 {len(by_staff)}名 / 合計 ¥{total_amount_sum:,}")

    # 10. 承認（全員）→ 支払済み（半分）→ 領収書発行（支払済み分）
    section("Step 8: 承認 → 支払 → 領収書発行")
    payments = db.get_payments_for_event(event_id)
    # 全員承認
    for p in payments:
        db.approve_payment(p["id"], "経理承認（E2E）", event_id)
    print(f"  ✅ 全 {len(payments)}名を承認済みに")

    # 上位50%を支払済み
    paid_ids = []
    for p in payments[:len(payments) // 2]:
        db.mark_paid(p["id"], event_id)
        paid_ids.append(p["id"])
    print(f"  ✅ {len(paid_ids)}名を支払済み(paid)に")

    # 支払済み全員の領収書発行
    section("Step 9: 領収書一括発行")
    t0 = time.time()
    result = receipt_issuer.issue_receipts_bulk(paid_ids, valid_days=14)
    dt = time.time() - t0
    print(f"  ✅ {result['success']}件発行成功 / {result['failure']}件失敗 ({dt:.1f}秒)")

    # 11. Petty Cash（雑費）も記録
    section("Step 10: 雑費記録")
    db.add_petty_cash(event_id, "2026-08-13", "スタッフ弁当代", 24000, "笹尾", "伊藤")
    db.add_petty_cash(event_id, "2026-08-14", "両替手数料", 1100, "笹尾", "伊藤")
    db.add_petty_cash(event_id, "2026-08-15", "文房具追加購入", 3200, "小島", "伊藤")
    db.add_petty_cash(event_id, "2026-08-17", "送迎タクシー", 8800, "笹尾", "伊藤")
    print("  ✅ 雑費4件")

    # サマリ
    section("セットアップ完了サマリ")
    print(f"  📋 イベント: {cfg['name']} (id={event_id})")
    print(f"  🧑 スタッフ: {len(staff_all)}名登録")
    print(f"  📅 シフト: {imported}件")
    print(f"  🕒 出退勤: 欠勤3・遅刻2・凍結退勤20名")
    print(f"  🚃 交通費: {count}件の領収書入力")
    print(f"  💰 支払い: {len(payments)}名計算・全員承認・半数paid")
    print(f"  📄 領収書発行: {result['success']}件")
    print(f"  💸 雑費: 4件")
    print(f"  💵 支払合計: ¥{total_amount_sum:,}")
    print()
    print("🔗 Streamlit Cloud URL:")
    print("   https://p1-staff-manager.streamlit.app")
    print()
    print("✅ データは残留状態で保存されました。cleanup不要時はこのスクリプトを再実行すると")
    print("   同名イベントのみ入れ替えます。完全に消したい場合は 2_run_e2e_test.py を走らせる")
    print("   か、Supabaseダッシュボードで削除してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
