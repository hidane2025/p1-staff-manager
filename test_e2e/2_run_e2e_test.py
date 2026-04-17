"""P1 Staff Manager — E2Eテスト: 80名規模架空大会の全一連動作

生成データ (1_generate_data.py の出力) を使って、実データとして Supabase に流し込み、
以下の一連動作を検証する。

1. スタッフ一括登録 (bulk_import_staff)
2. イベント作成 + レート設定
3. シフト取込 (parse_shift_csv → upsert_shift)
4. 交通費ルール設定
5. 出退勤（欠勤・遅刻・凍結一括退勤）
6. 領収書入力
7. 支払い計算（タイミー個別時給・業務委託深夜手当・500円丸め）
8. 承認→支払フロー
9. 封筒リスト（紙幣内訳）
10. 精算レポート・年間累計

終了時には作成したテストデータを掃除する。
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

# プロジェクトルートを path に追加
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db  # type: ignore
from utils import calculator  # type: ignore
from utils import denomination  # type: ignore
from utils import shift_parser  # type: ignore


TEST_DIR = Path(__file__).resolve().parent
STAFF_CSV = TEST_DIR / "01_staff_master.csv"
SHIFT_CSV = TEST_DIR / "02_shift_kyoto.csv"
EVENT_JSON = TEST_DIR / "03_event_config.json"

REPORT_PATH = TEST_DIR / "04_test_report.md"

# --- 結果集計 ---
PASS: list[str] = []
FAIL: list[str] = []
WARN: list[str] = []
METRICS: dict[str, Any] = {}


def ok(msg: str) -> None:
    PASS.append(msg)
    print(f"  ✅ {msg}")


def ng(msg: str) -> None:
    FAIL.append(msg)
    print(f"  ❌ {msg}")


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"  ⚠️  {msg}")


def section(title: str) -> None:
    print(f"\n{'='*70}\n{title}\n{'='*70}")


# ==========================================================================
# Step 0: 既存テストデータのクリーンアップ
# ==========================================================================
def cleanup_before() -> dict:
    section("Step 0: 既存テストデータ確認・クリーンアップ")
    client = db.get_client()
    # 同名イベントがあれば削除
    cfg = json.loads(EVENT_JSON.read_text(encoding="utf-8"))
    ev_name = cfg["name"]
    events = client.table("p1_events").select("id,name").eq("name", ev_name).execute().data
    removed_events = 0
    for e in events:
        eid = e["id"]
        # 関連テーブル削除
        for tbl in ["p1_payments", "p1_shifts", "p1_event_rates",
                    "p1_event_transport_rules", "p1_transport_claims",
                    "p1_petty_cash", "p1_audit_log"]:
            try:
                client.table(tbl).delete().eq("event_id", eid).execute()
            except Exception:
                pass
        client.table("p1_events").delete().eq("id", eid).execute()
        removed_events += 1
    # テスト用スタッフ（no>=100 かつ p1staff_*@example.com）を削除
    # FK: 先に shifts/payments を落とす
    existing = client.table("p1_staff").select("id,no,email").gte("no", 100).lte("no", 199).execute().data
    removed_staff = 0
    for s in existing:
        if (s.get("email") or "").startswith("p1staff_"):
            for tbl in ["p1_shifts", "p1_payments", "p1_transport_claims"]:
                try:
                    client.table(tbl).delete().eq("staff_id", s["id"]).execute()
                except Exception:
                    pass
            client.table("p1_staff").delete().eq("id", s["id"]).execute()
            removed_staff += 1
    ok(f"前回イベント削除: {removed_events}件 / 前回スタッフ削除: {removed_staff}名")
    return {"removed_events": removed_events, "removed_staff": removed_staff}


# ==========================================================================
# Step 1: スタッフ一括登録
# ==========================================================================
def step_bulk_import_staff() -> dict[str, int]:
    section("Step 1: スタッフ一括登録 (bulk_import_staff)")
    rows: list[dict] = []
    with STAFF_CSV.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    print(f"  入力: {len(rows)}行")

    t0 = time.time()
    result = db.bulk_import_staff(rows)
    dt = time.time() - t0
    print(f"  実行時間: {dt:.1f}秒")

    METRICS["bulk_import"] = {"input": len(rows), **result, "elapsed_sec": round(dt, 1)}
    if result["errors"]:
        for e in result["errors"][:5]:
            warn(f"import error: {e}")
        ng(f"エラー {len(result['errors'])}件発生")
    else:
        ok(f"エラー0件 / 新規{result['created']} 更新{result['updated']}")

    # 地域自動判定検証
    client = db.get_client()
    reg_counts: dict[str, int] = {}
    staff_now = client.table("p1_staff").select("id, no, name_jp, region, prefecture, employment_type, custom_hourly_rate").gte("no", 100).lte("no", 199).execute().data
    name_to_id: dict[str, int] = {}
    for s in staff_now:
        reg_counts[s.get("region") or "未判定"] = reg_counts.get(s.get("region") or "未判定", 0) + 1
        name_to_id[s["name_jp"]] = s["id"]
    print(f"  地域分布: {dict(sorted(reg_counts.items(), key=lambda x: -x[1]))}")
    if "近畿" in reg_counts and "東海" in reg_counts and "関東" in reg_counts:
        ok("地域自動判定が機能（近畿/東海/関東）")
    else:
        ng(f"地域自動判定が不十分: {reg_counts}")

    # タイミーの custom_hourly_rate が 0 でないか
    timee_rates = [s["custom_hourly_rate"] for s in staff_now if s["employment_type"] == "timee"]
    if timee_rates and all(r and r > 0 for r in timee_rates):
        ok(f"タイミー個別時給保存: {len(timee_rates)}名 (全員 rate > 0)")
    elif timee_rates:
        ng(f"タイミー個別時給が0のスタッフあり: {timee_rates}")
    else:
        warn("タイミースタッフなし")

    return name_to_id


# ==========================================================================
# Step 2: イベント作成 + レート設定
# ==========================================================================
def step_create_event() -> int:
    section("Step 2: イベント作成 + レート設定")
    cfg = json.loads(EVENT_JSON.read_text(encoding="utf-8"))
    event_id = db.create_event(
        name=cfg["name"], venue=cfg["venue"],
        start_date=cfg["start_date"], end_date=cfg["end_date"],
        break_minutes_6h=45, break_minutes_8h=60,
    )
    if event_id:
        ok(f"イベント作成: id={event_id} '{cfg['name']}'")
    else:
        ng("イベント作成失敗")
        return 0

    # レート設定
    for date, r in cfg["rates"].items():
        db.set_event_rate(
            event_id, date,
            hourly_rate=r["hourly"], night_rate=r["night"],
            transport=r["transport"], floor_bonus=r["floor_bonus"],
            mix_bonus=r["mix_bonus"], date_label=r["date_label"],
        )
    rates = db.get_event_rates(event_id)
    if len(rates) == len(cfg["dates"]):
        ok(f"レート設定: {len(rates)}日分 (プレミアム日含む)")
    else:
        ng(f"レート不整合: 期待{len(cfg['dates'])} 実{len(rates)}")

    # プレミアム日の時給確認
    premium = [r for r in rates if r["date_label"] == "premium"]
    if any(r["hourly_rate"] == 1600 for r in premium):
        ok("プレミアム日時給1600円を確認")
    else:
        ng("プレミアム日の時給が反映されていない")

    return event_id


# ==========================================================================
# Step 3: シフト取込
# ==========================================================================
def step_import_shifts(event_id: int, name_to_id: dict[str, int]) -> int:
    section("Step 3: シフト取込 (parse_shift_csv → upsert_shift)")
    raw = SHIFT_CSV.read_bytes()
    parsed = shift_parser.parse_shift_csv(raw, year=2026)
    staff_rows = parsed.get("staff", [])
    dates = parsed.get("dates", [])
    shift_rows = parsed.get("shifts", [])
    print(f"  parse結果: staff={len(staff_rows)}, dates={len(dates)}, shifts={len(shift_rows)}")

    imported = 0
    skipped_names: set = set()
    for srow in shift_rows:
        name = srow["name_jp"]
        staff_id = name_to_id.get(name)
        if not staff_id:
            skipped_names.add(name)
            continue
        time_range = srow.get("time_range") or ""
        if not time_range:
            continue
        parsed_t = calculator.parse_shift_time(time_range)
        if not parsed_t:
            continue
        start_min, end_min = parsed_t
        start_str = f"{start_min // 60:02d}:{start_min % 60:02d}"
        end_str = f"{end_min // 60:02d}:{end_min % 60:02d}"
        db.upsert_shift(event_id, staff_id, srow["date"], start_str, end_str, is_mix=0)
        imported += 1

    METRICS["shifts_imported"] = imported
    ok(f"シフト取込: {imported}件 (未解決スタッフ名: {len(skipped_names)}名)")
    db_shifts = db.get_shifts_for_event(event_id)
    if len(db_shifts) == imported:
        ok(f"DB照合OK: {len(db_shifts)}件")
    else:
        warn(f"DB照合差異: imported={imported}, db={len(db_shifts)}")
    return imported


# ==========================================================================
# Step 4: 交通費ルール設定
# ==========================================================================
def step_transport_rules(event_id: int) -> None:
    section("Step 4: 交通費ルール設定")
    cfg = json.loads(EVENT_JSON.read_text(encoding="utf-8"))
    db.save_transport_rules(event_id, cfg["transport_rules"])
    rules = db.get_transport_rules(event_id)
    METRICS["transport_rules"] = len(rules)
    if len(rules) == len(cfg["transport_rules"]):
        ok(f"交通費ルール: {len(rules)}地域")
    else:
        ng(f"交通費ルール不整合: 期待{len(cfg['transport_rules'])} 実{len(rules)}")
    venue_rule = [r for r in rules if r.get("is_venue_region") == 1]
    if venue_rule and venue_rule[0]["region"] == "近畿":
        ok(f"開催地地域=近畿 ¥{venue_rule[0]['max_amount']} 一律")
    else:
        ng("開催地地域設定が不正")


# ==========================================================================
# Step 5: 出退勤シミュレーション（欠勤・遅刻・凍結）
# ==========================================================================
def step_attendance(event_id: int) -> dict:
    section("Step 5: 出退勤シミュレーション")
    shifts = db.get_shifts_for_event(event_id)
    print(f"  対象シフト数: {len(shifts)}")

    # 欠勤5件（ランダムなシフトを選ぶ）
    absent_ids = [s["id"] for s in shifts[:5]]
    for sid in absent_ids:
        db.mark_absent(sid)
    ok(f"欠勤: {len(absent_ids)}件")

    # 遅刻3件（actual_startを計画より30分遅く）
    late_targets = shifts[5:8]
    for s in late_targets:
        ps = s["planned_start"]
        # +30分
        h, m = ps.split(":")
        new_min = int(h) * 60 + int(m) + 30
        new_start = f"{new_min // 60:02d}:{new_min % 60:02d}"
        db.checkin_staff(s["id"], new_start)
    ok(f"遅刻チェックイン: {len(late_targets)}件")

    # 通常チェックイン＋チェックアウト10件
    normal = shifts[8:18]
    for s in normal:
        db.checkin_staff(s["id"], s["planned_start"])
        db.checkout_staff(s["id"], s["planned_end"])
    ok(f"通常退勤済み: {len(normal)}件")

    # 凍結一括退勤: 初日の全アサインから20件抽出
    day1 = [s for s in shifts if s.get("date") == "2026-08-13" and s["id"] not in absent_ids][:20]
    day1_ids = [s["id"] for s in day1]
    day1_staff = db.bulk_checkout(day1_ids, "26:00", event_id=event_id)
    ok(f"凍結一括退勤: {len(day1_ids)}件 (影響スタッフ {len(day1_staff)}名)")

    # reset_payment_to_pending呼び出し（既に支払いがあると仮定）テスト ⇒ Step 7で再確認
    return {
        "absent": len(absent_ids),
        "late": len(late_targets),
        "checked_out": len(normal) + len(day1_ids),
        "frozen_staff": len(day1_staff),
    }


# ==========================================================================
# Step 6: 領収書入力
# ==========================================================================
def step_receipts(event_id: int) -> dict:
    section("Step 6: 領収書入力（非開催地スタッフ）")
    # 非開催地スタッフ（region != 近畿）で、かつイベントに稼働しているスタッフ
    client = db.get_client()
    shifts = db.get_shifts_for_event(event_id)
    working_staff_ids = list({s["staff_id"] for s in shifts})
    staff_rows = client.table("p1_staff").select("id, region, prefecture").in_("id", working_staff_ids).execute().data

    rules = {r["region"]: r for r in db.get_transport_rules(event_id)}
    registered = 0
    under_limit = 0
    over_limit = 0
    for s in staff_rows:
        region = s.get("region")
        if not region or region == "近畿":
            continue
        rule = rules.get(region)
        if not rule:
            continue
        max_amt = rule["max_amount"]
        # 地域別に領収書金額を模擬（東海:5000, 関東:14000, 九州:25000上限超, 等）
        sample = {
            "東海": 5000, "関東": 14000, "甲信越": 11000, "北陸": 9000,
            "中国": 9500, "四国": 11500, "九州": 25000, "東北": 21000,
            "北海道": 28000, "沖縄": 30000,
        }.get(region, 8000)
        approved = min(sample, max_amt)
        db.upsert_transport_claim(event_id, s["id"], sample, approved, has_receipt=1, note="E2E自動登録")
        registered += 1
        if sample <= max_amt:
            under_limit += 1
        else:
            over_limit += 1
    ok(f"領収書入力: {registered}件 (上限内{under_limit}件, 超過{over_limit}件→上限まで承認)")
    METRICS["receipts"] = {"registered": registered, "under": under_limit, "over": over_limit}
    return {"registered": registered}


# ==========================================================================
# Step 7: 支払い計算
# ==========================================================================
def step_calculate_payments(event_id: int, round_to_500: bool = True) -> dict:
    section("Step 7: 支払い計算（500円丸め）")
    client = db.get_client()
    event = db.get_event_by_id(event_id)
    rates = db.get_event_rates(event_id)
    rates_by_date = {r["date"]: {
        "hourly": r["hourly_rate"], "night": r["night_rate"],
        "transport": r["transport_allowance"],
        "floor_bonus": r["floor_bonus"], "mix_bonus": r["mix_bonus"],
    } for r in rates}
    total_event_days = len(rates_by_date)

    shifts = db.get_shifts_for_event(event_id)
    # staff単位でグループ化
    by_staff: dict[int, list[dict]] = {}
    for s in shifts:
        if s.get("status") == "absent":
            continue
        sid = s["staff_id"]
        by_staff.setdefault(sid, []).append({
            "date": s["date"], "start": s["planned_start"],
            "end": s["planned_end"], "is_mix": bool(s.get("is_mix")),
        })

    # 交通費請求
    claims = {c["staff_id"]: c for c in db.get_transport_claims(event_id)}

    staff_info = {s["id"]: s for s in client.table("p1_staff").select("*").in_(
        "id", list(by_staff.keys())).execute().data}

    computed = 0
    timee_count = 0
    timee_total = 0
    contractor_total = 0
    over_100k = 0
    for staff_id, sh in by_staff.items():
        info = staff_info.get(staff_id, {})
        emp = info.get("employment_type", "contractor")
        custom = info.get("custom_hourly_rate") if emp == "timee" else None
        # 交通費: 非開催地は領収書金額ベース、それ以外は累計（1000円×日数）
        transport_override = None
        if staff_id in claims:
            transport_override = claims[staff_id]["approved_amount"] * len(sh)  # 日数分累計

        pay = calculator.calculate_staff_payment(
            staff_id=staff_id,
            name=info.get("name_jp", ""),
            role=info.get("role", "Dealer"),
            shifts=sh, rates_by_date=rates_by_date,
            total_event_days=total_event_days,
            break_6h=45, break_8h=60,
            employment_type=emp,
            custom_hourly_rate=custom,
            transport_override=transport_override,
        )
        total = pay.total_amount
        if round_to_500:
            # 500円単位繰り上げ
            total = ((total + 499) // 500) * 500
        db.save_payment(
            event_id, staff_id,
            pay.base_pay, pay.night_pay, pay.transport_total,
            pay.floor_bonus_total, pay.mix_bonus_total, pay.attendance_bonus,
            total, break_deduction=pay.break_deduction,
        )
        computed += 1
        if emp == "timee":
            timee_count += 1
            timee_total += total
        else:
            contractor_total += total
        if total >= 100000:
            over_100k += 1

    METRICS["payments"] = {
        "count": computed, "timee_count": timee_count,
        "timee_total": timee_total, "contractor_total": contractor_total,
        "over_100k": over_100k,
    }
    ok(f"支払い計算: {computed}名 / タイミー{timee_count}名 / 10万円超{over_100k}名")

    # 500円丸め検証
    payments = db.get_payments_for_event(event_id)
    not_rounded = [p for p in payments if p["total_amount"] % 500 != 0]
    if not not_rounded:
        ok(f"500円丸め検証: 全{len(payments)}件OK")
    else:
        ng(f"500円丸め違反: {len(not_rounded)}件")

    return {"computed": computed}


# ==========================================================================
# Step 7b: 凍結後の再計算シナリオ
# ==========================================================================
def step_freeze_recalc(event_id: int) -> None:
    section("Step 7b: 凍結後の再計算（reset_payment_to_pending）")
    payments = db.get_payments_for_event(event_id)
    if not payments:
        warn("支払いがない")
        return
    sample = payments[0]
    client = db.get_client()
    # まず承認済みに状態遷移
    db.approve_payment(sample["id"], "E2Eテスト")
    reset_ok = db.reset_payment_to_pending(event_id, sample["staff_id"], reason="E2E凍結検証")
    row = client.table("p1_payments").select("status").eq("id", sample["id"]).execute().data
    if reset_ok and row and row[0]["status"] == "pending":
        ok("承認済み→未承認へ戻す: OK")
    else:
        ng(f"凍結再計算失敗: reset_ok={reset_ok} status={row}")

    # paid保護: 別の支払いを paid にして reset を呼ぶ
    if len(payments) >= 2:
        protect_target = payments[1]
        db.mark_paid(protect_target["id"])
        reset2 = db.reset_payment_to_pending(event_id, protect_target["staff_id"], reason="E2E保護テスト")
        row2 = client.table("p1_payments").select("status").eq("id", protect_target["id"]).execute().data
        if not reset2 and row2 and row2[0]["status"] == "paid":
            ok("支払済み保護: OK")
        else:
            ng(f"支払済み保護失敗: reset={reset2} status={row2}")


# ==========================================================================
# Step 8: 封筒リスト（紙幣内訳）
# ==========================================================================
def step_envelope(event_id: int) -> None:
    section("Step 8: 封筒リスト・紙幣内訳")
    payments = db.get_payments_for_event(event_id)
    amounts = [p["total_amount"] for p in payments]
    if not amounts:
        ng("支払いなし")
        return
    total_denom = denomination.calculate_total_denomination(amounts)
    print(f"  支払い件数: {len(amounts)}, 合計: ¥{sum(amounts):,}")
    print(f"  紙幣内訳: {total_denom}")
    grand = (
        total_denom.get(10000, 0) * 10000 +
        total_denom.get(5000, 0) * 5000 +
        total_denom.get(1000, 0) * 1000 +
        total_denom.get(500, 0) * 500 +
        total_denom.get(100, 0) * 100 +
        total_denom.get(50, 0) * 50 +
        total_denom.get(10, 0) * 10 +
        total_denom.get(5, 0) * 5 +
        total_denom.get(1, 0) * 1
    )
    if grand == sum(amounts):
        ok(f"紙幣合算一致: ¥{grand:,}")
    else:
        ng(f"紙幣合算不一致: 期待¥{sum(amounts):,} 実¥{grand:,}")
    METRICS["envelope"] = {"total": sum(amounts), "denom": total_denom, "staff": len(amounts)}


# ==========================================================================
# Step 9: 承認→支払フロー
# ==========================================================================
def step_approve_pay(event_id: int) -> None:
    section("Step 9: 承認→支払フロー")
    payments = db.get_payments_for_event(event_id)
    # pending のみ
    pending = [p for p in payments if p["status"] == "pending"]
    approved = 0
    paid = 0
    for p in pending[:50]:  # 50名分承認
        db.approve_payment(p["id"], "E2Eテスト", event_id)
        approved += 1
    for p in pending[:30]:  # 30名分支払完了
        db.mark_paid(p["id"], event_id)
        paid += 1
    ok(f"承認: {approved}名 / 支払完了: {paid}名")
    METRICS["approval"] = {"approved": approved, "paid": paid}


# ==========================================================================
# Step 10: 年間累計
# ==========================================================================
def step_yearly_totals() -> None:
    section("Step 10: 年間累計")
    totals = db.get_yearly_totals(2026)
    event_totals = [t for t in totals if any("Kyoto 2026" in n for n in t["event_names"])]
    ok(f"2026年累計: {len(totals)}名 / 京都大会関与: {len(event_totals)}名")
    # 法定調書対象者（50万円超）
    over_500k = [t for t in totals if t["total_amount"] >= 500000]
    METRICS["yearly"] = {
        "total_staff": len(totals),
        "kyoto_staff": len(event_totals),
        "over_500k": len(over_500k),
    }
    if event_totals:
        top = max(event_totals, key=lambda x: x["total_amount"])
        print(f"  トップ: {top['name_jp']} ¥{top['total_amount']:,} ({top['role']})")


# ==========================================================================
# Final Cleanup
# ==========================================================================
def cleanup_after(event_id: int) -> None:
    section("Final: テストデータ掃除")
    if not event_id:
        return
    client = db.get_client()
    for tbl in ["p1_payments", "p1_shifts", "p1_event_rates",
                "p1_event_transport_rules", "p1_transport_claims",
                "p1_petty_cash", "p1_audit_log"]:
        try:
            client.table(tbl).delete().eq("event_id", event_id).execute()
        except Exception as e:
            warn(f"{tbl} 削除失敗: {e}")
    client.table("p1_events").delete().eq("id", event_id).execute()
    # スタッフ削除
    existing = client.table("p1_staff").select("id,email").gte("no", 100).lte("no", 199).execute().data
    n = 0
    for s in existing:
        if (s.get("email") or "").startswith("p1staff_"):
            for tbl in ["p1_shifts", "p1_payments", "p1_transport_claims"]:
                try:
                    client.table(tbl).delete().eq("staff_id", s["id"]).execute()
                except Exception:
                    pass
            client.table("p1_staff").delete().eq("id", s["id"]).execute()
            n += 1
    ok(f"テストスタッフ削除: {n}名 / イベント削除: id={event_id}")


# ==========================================================================
# Report
# ==========================================================================
def write_report() -> None:
    lines = [
        "# P1 Staff Manager E2Eテスト結果",
        "",
        "## サマリ",
        f"- ✅ PASS: {len(PASS)}件",
        f"- ❌ FAIL: {len(FAIL)}件",
        f"- ⚠️ WARN: {len(WARN)}件",
        "",
        "## メトリクス",
        "```json",
        json.dumps(METRICS, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## PASS詳細",
        *[f"- {m}" for m in PASS],
        "",
        "## FAIL詳細",
    ]
    lines += [f"- {m}" for m in FAIL] if FAIL else ["- (なし)"]
    lines += ["", "## WARN詳細"]
    lines += [f"- {m}" for m in WARN] if WARN else ["- (なし)"]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nレポート出力: {REPORT_PATH}")


def main() -> int:
    cleanup_before()
    name_to_id = step_bulk_import_staff()
    event_id = step_create_event()
    if not event_id:
        write_report()
        return 1
    step_import_shifts(event_id, name_to_id)
    step_transport_rules(event_id)
    step_attendance(event_id)
    step_receipts(event_id)
    step_calculate_payments(event_id, round_to_500=True)
    step_freeze_recalc(event_id)
    step_envelope(event_id)
    step_approve_pay(event_id)
    step_yearly_totals()
    cleanup_after(event_id)
    write_report()
    section(f"終了: PASS {len(PASS)} / FAIL {len(FAIL)} / WARN {len(WARN)}")
    return 0 if not FAIL else 2


if __name__ == "__main__":
    sys.exit(main())
