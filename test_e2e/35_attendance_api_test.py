"""勤怠受信API（api/attendance_api.py）の単体テスト — DB・ネットワーク非依存

P1会員アプリ（TAKAさん側）との連携仕様を固定する:
  認証二重（Basic＋X-API-Key）／attendance_keyフィールドの受理／
  深夜跨ぎの日付解決／24時超表記への変換／順不同再送の破棄（updated_at）／
  実績変更時の支払い差し戻し
"""
from __future__ import annotations

import os
import pathlib
import sys
from base64 import b64encode

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ["ATTENDANCE_API_USER"] = "test-user"
os.environ["ATTENDANCE_API_PASSWORD"] = "test-pass"
os.environ["ATTENDANCE_API_KEY"] = "test-key-123"

from fastapi.testclient import TestClient  # noqa: E402

import api.attendance_api as m  # noqa: E402

failures: list = []


def _check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + ("" if cond else f" — {detail}"))
    if not cond:
        failures.append(name)


def _auth(user="test-user", pw="test-pass", key="test-key-123"):
    h = {"Authorization": "Basic " + b64encode(f"{user}:{pw}".encode()).decode()}
    if key is not None:
        h["X-API-Key"] = key
    return h


class _FakeTable:
    def __init__(self, log):
        self.log = log
        self._op = None
        self._payload = None

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def eq(self, *a):
        return self

    def execute(self):
        self.log.append((self._op, self._payload))
        return type("R", (), {"data": []})()


class _FakeClient:
    def __init__(self, log):
        self.log = log

    def table(self, name):
        return _FakeTable(self.log)


def _run(payload, staff=None, rows=None, event=None):
    """1リクエスト実行し (response, 書き込みログ, revert回数) を返す"""
    writes: list = []
    reverts: list = []
    olds = (m._staff_by_no, m._shift_rows, m._event_for_date,
            m.db.get_client, m.db.log_action, m._revert_payment_if_amount_affected)
    m._staff_by_no = lambda no: staff
    m._shift_rows = lambda sid, dates: [r for r in (rows or []) if r["date"] in dates]
    m._event_for_date = lambda d: event
    m.db.get_client = lambda: _FakeClient(writes)
    m.db.log_action = lambda *a, **k: None
    m._revert_payment_if_amount_affected = lambda *a, **k: reverts.append(1)
    try:
        c = TestClient(m.app, raise_server_exceptions=False)
        res = c.post("/api/attendance", json=payload, headers=_auth())
        return res, writes, len(reverts)
    finally:
        (m._staff_by_no, m._shift_rows, m._event_for_date,
         m.db.get_client, m.db.log_action,
         m._revert_payment_if_amount_affected) = olds


BASE = {"attendance_key": "p1-5-23-123", "dealer_number": "0055",
        "clock_in_at": "2026-08-13T12:03:00+09:00",
        "clock_out_at": "2026-08-13T22:17:00+09:00",
        "updated_at": "2026-08-13T22:17:10+09:00"}
STAFF = {"id": 501, "no": 55, "name_jp": "テスト55"}

print("\n[認証]")
c = TestClient(m.app, raise_server_exceptions=False)
_check("死活は認証なしで200", c.get("/api/health").status_code == 200)
r = c.post("/api/attendance", json=BASE)
_check("認証なしPOSTは401＋retry:false", r.status_code == 401
       and r.json()["detail"]["retry"] is False, str(r.json()))
r = c.post("/api/attendance", json=BASE, headers=_auth(key="wrong"))
_check("APIキー誤りは403", r.status_code == 403, str(r.status_code))
r = c.post("/api/attendance", json=BASE, headers=_auth(pw="wrong"))
_check("Basic誤りは401", r.status_code == 401, str(r.status_code))

print("\n[入力検証]")
bad = dict(BASE, clock_in_at="2026-08-13T12:03:00")  # タイムゾーンなし
res, w, _ = _run(bad, staff=STAFF)
_check("タイムゾーンなしは422", res.status_code == 422, str(res.status_code))
res, w, _ = _run(dict(BASE, dealer_number="abc"), staff=STAFF)
_check("数値でない番号は422", res.status_code == 422, str(res.status_code))
res, w, _ = _run(BASE, staff=None)
_check("未知のディーラー番号は404＋retry:false", res.status_code == 404
       and res.json()["detail"]["retry"] is False, str(res.json()))

print("\n[新規作成（シフト行なし＝当日追加）]")
res, w, rv = _run(dict(BASE, clock_out_at=None), staff=STAFF,
                  event={"id": 11, "start_date": "2026-08-12", "end_date": "2026-08-16"})
_check("200＋action=created", res.status_code == 200
       and res.json()["action"] == "created", str(res.json()))
ins = w[0][1]
_check("出勤のみ→actual_end無し・checked_in", w[0][0] == "insert"
       and ins["actual_start"] == "12:03" and ins["actual_end"] is None
       and ins["status"] == "checked_in", str(ins))
_check("予定が空にならない（支払い計算の対象に入る）",
       ins["planned_start"] == "12:03" and ins["planned_end"] == "12:03", str(ins))
_check("attendance_keyとupdated_atがnotesに残る",
       "p1-5-23-123" in ins["notes"] and "updated=" in ins["notes"], str(ins))

print("\n[更新（upsert）]")
ROW = {"id": 9, "event_id": 11, "staff_id": 501, "date": "2026-08-13",
       "actual_start": "12:03", "actual_end": None, "status": "checked_in",
       "notes": "〔API連携 key=p1-5-23-123 updated=2026-08-13T12:03:05+09:00〕"}
res, w, rv = _run(BASE, staff=STAFF, rows=[ROW])
upd = w[0][1]
_check("退勤更新→actual_end=22:17・checked_out", res.json()["action"] == "updated"
       and upd["actual_end"] == "22:17" and upd["status"] == "checked_out", str(upd))
_check("実績が変わったので支払い差し戻しが呼ばれる", rv == 1, str(rv))
_check("markerが新しいupdated_atへ置き換わる",
       "updated=2026-08-13T22:17:10+09:00" in upd["notes"], str(upd["notes"]))

print("\n[順不同の再送]")
newer = dict(ROW, notes="〔API連携 key=k updated=2026-08-13T23:00:00+09:00〕")
res, w, rv = _run(BASE, staff=STAFF, rows=[newer])
_check("古いupdated_atはskipped_stale（書き込みなし）",
       res.json()["action"] == "skipped_stale" and not w and rv == 0,
       f"{res.json()} writes={len(w)}")

print("\n[深夜跨ぎ]")
ov = dict(BASE, clock_in_at="2026-08-12T18:00:00+09:00",
          clock_out_at="2026-08-13T06:00:00+09:00",
          updated_at="2026-08-13T06:00:05+09:00")
row12 = dict(ROW, date="2026-08-12", notes="")
res, w, rv = _run(ov, staff=STAFF, rows=[row12])
upd = w[0][1]
_check("8/12 18:00〜翌6:00 → 18:00〜30:00（8/12の行）",
       res.json()["date"] == "2026-08-12"
       and upd["actual_start"] == "18:00" and upd["actual_end"] == "30:00", str(upd))
late = dict(BASE, clock_in_at="2026-08-13T00:30:00+09:00", clock_out_at=None,
            updated_at="2026-08-13T00:30:05+09:00")
res, w, rv = _run(late, staff=STAFF, rows=[row12])
_check("深夜0:30の出勤は前日(8/12)の行に 24:30 で入る",
       res.json()["date"] == "2026-08-12" and w[0][1]["actual_start"] == "24:30",
       str(w[0][1]))

print("\n[再打刻（退勤の取り消し）]")
done = dict(ROW, actual_end="22:17", status="checked_out", notes="")
res, w, rv = _run(dict(BASE, clock_out_at=None,
                       updated_at="2026-08-13T23:30:00+09:00"),
                  staff=STAFF, rows=[done])
_check("退勤nullの再送で checked_in に戻る",
       w[0][1]["actual_end"] is None and w[0][1]["status"] == "checked_in", str(w[0][1]))

print()
print("=" * 60)
if failures:
    print(f"❌ 失敗 {len(failures)}件: {failures}")
    sys.exit(1)
print("✅ 全テスト成功")
