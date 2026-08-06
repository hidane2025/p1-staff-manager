"""操作マニュアル撮影用のデモデータを作る（実在の個人情報は使わない）

架空のディーラーネーム・架空住所のみ。撮影後は teardown で完全削除する。
使い方: python seed_demo.py <setup|teardown>
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path.home() / "Documents/GitHub/p1-staff-manager"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
IDS = pathlib.Path(__file__).parent / "demo_ids.json"

EVENT = "【操作説明用】P1 CIRCUIT デモ大会"
DAYS = ["2026-09-01", "2026-09-02"]

# 架空のディーラーネーム（実在の人物とは無関係）
STAFF = [
    (9101, "サンプル太郎", "Sample Taro", "Dealer", "大阪府大阪市北区梅田1-1-1",
     [(0, "13:00", "22:00", 0), (1, "13:00", "22:00", 0)]),
    (9102, "デモ花子", "Demo Hanako", "Dealer", "大阪府堺市堺区1-2-3",
     [(0, "18:00", "27:00", 0), (1, "18:00", "27:00", 0)]),
    (9103, "テスト次郎", "Test Jiro", "Floor", "愛知県名古屋市中村区2-2",
     [(0, "13:00", "23:00", 0), (1, "13:00", "23:00", 0)]),
    (9104, "見本三郎", "Mihon Saburo", "Dealer", "東京都渋谷区3-3",
     [(0, "15:00", "24:00", 1)]),
    (9105, "例示四郎", "Reiji Shiro", "Dealer", "兵庫県神戸市中央区4-4",
     [(0, "13:00", "22:00", 0), (1, "13:00", "20:00", 0)]),
    (9106, "架空五郎", "Kakuu Goro", "Dealer", "福岡県福岡市博多区5-5",
     [(1, "13:00", "22:00", 0)]),
]

RULES = [
    ("北海道", 30000, 1, 0), ("東北", 30000, 1, 0), ("関東", 25000, 1, 0),
    ("甲信越", 25000, 1, 0), ("北陸", 25000, 1, 0), ("東海", 15000, 1, 0),
    ("近畿", 1000, 0, 1), ("中国", 25000, 1, 0), ("四国", 15000, 1, 0),
    ("九州", 30000, 1, 0), ("沖縄", 30000, 1, 0),
]


def setup():
    import db
    ev = db.create_event(EVENT, "ヒルトン大阪（デモ）", DAYS[0], DAYS[-1], 0, 0,
                         prefecture="大阪府")
    for d in DAYS:
        db.set_event_rate(ev, d, hourly_rate=1500, night_rate=1875, transport=0,
                          floor_bonus=3000, mix_bonus=1500)
    db.save_transport_rules(ev, [
        {"region": r, "max_amount": m, "receipt_required": rq,
         "is_venue_region": v, "note": ""} for r, m, rq, v in RULES])
    data = {"event": ev, "staff": {}}
    for no, jp, en, role, addr, shifts in STAFF:
        sid = db.create_staff(no, jp, name_en=en, role=role, address=addr,
                              real_name=f"見本 {jp}", email=f"demo{no}@example.invalid",
                              employment_type="contractor")
        data["staff"][str(no)] = sid
        for di, s, e, mix in shifts:
            db.upsert_shift(ev, sid, DAYS[di], s, e, is_mix=mix)
    # 交通費の領収書（遠方2名）を入れておく
    db.upsert_transport_claim(ev, data["staff"]["9103"], receipt_amount=12000,
                              approved_amount=12000, has_receipt=1, note="新幹線往復")
    db.upsert_transport_claim(ev, data["staff"]["9104"], receipt_amount=28000,
                              approved_amount=25000, has_receipt=1, note="上限調整")
    # 個別手当の例
    db.add_individual_allowance(ev, data["staff"]["9103"], "language", 5000,
                                note="英語対応", created_by="デモ")
    IDS.write_text(json.dumps(data))
    print(f"デモ準備完了: event={ev} / スタッフ{len(STAFF)}名 / シフト"
          f"{len(db.get_shifts_for_event(ev))}本")


def teardown():
    import db
    d = json.loads(IDS.read_text())
    c = db.get_client()
    for t in ("p1_payments", "p1_transport_claims", "p1_shifts",
              "p1_event_transport_rules", "p1_event_rates", "p1_audit_log",
              "p1_staff_event_allowances", "p1_contracts"):
        try:
            c.table(t).delete().eq("event_id", d["event"]).execute()
        except Exception:
            pass
    for sid in d["staff"].values():
        for t in ("p1_staff_event_allowances", "p1_contracts"):
            try:
                c.table(t).delete().eq("staff_id", sid).execute()
            except Exception:
                pass
        c.table("p1_staff").delete().eq("id", sid).execute()
    c.table("p1_events").delete().eq("id", d["event"]).execute()
    left = c.table("p1_staff").select("id", count="exact").gte("no", 9000).execute().count
    print("削除完了。NO.9000以上の残存:", left)


if __name__ == "__main__":
    {"setup": setup, "teardown": teardown}[sys.argv[1]]()
