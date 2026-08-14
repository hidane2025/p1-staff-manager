"""勤怠受信API（api/attendance_api.py v2）の単体テスト — DB・ネットワーク非依存

P1会員アプリ（TAKAさん 2026-08-13 15時版仕様）との契約を固定する:
  認証がすべてに先行（ミドルウェア）／p1_shifts語彙のペイロード／
  (event,staff,date) upsert／null戻し／24時超表記／順不同再送の破棄／
  実績変更時の支払い差し戻し／一意制約なしDBでの重複行の扱い
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
    writes: list = []
    reverts: list = []
    olds = (m._staff_by_no, m._shift_rows, m._event_for_date,
            m.db.get_client, m.db.log_action, m._revert_payment_if_amount_affected)
    m._staff_by_no = lambda no: staff
    m._shift_rows = lambda sid, date: list(rows or [])
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


BASE = {"event_id": 11, "dealer_number": "0055", "date": "2026-08-12",
        "actual_start": "12:03", "actual_end": "25:17"}
STAFF = {"id": 501, "no": 55, "name_jp": "テスト55"}
ROW = {"id": 9, "event_id": 11, "staff_id": 501, "date": "2026-08-12",
       "actual_start": None, "actual_end": None, "status": "scheduled",
       "planned_start": "12:00", "planned_end": "25:00", "notes": ""}

print("\n[認証が本文検証より先に走る（v1バグの再発防止）]")
c = TestClient(m.app, raise_server_exceptions=False)
_check("死活は認証なしで200", c.get("/api/health").status_code == 200)
r = c.post("/api/attendance", json={})
_check("認証なし＋壊れた本文でも 401（422にならない）", r.status_code == 401,
       str(r.status_code))
r = c.post("/api/attendance", json=BASE, headers=_auth(key="wrong"))
_check("APIキー誤りは403", r.status_code == 403, str(r.status_code))
r = c.post("/api/attendance", json=BASE, headers=_auth(pw="wrong"))
_check("Basic誤りは401", r.status_code == 401, str(r.status_code))

print("\n[入力検証（先方仕様の形式）]")
res, w, _ = _run(dict(BASE, date="2026/08/12"), staff=STAFF)
_check("dateの形式違いは422", res.status_code == 422, str(res.status_code))
res, w, _ = _run(dict(BASE, actual_end="9:99"), staff=STAFF)
_check("時刻の形式違いは422", res.status_code == 422, str(res.status_code))
res, w, _ = _run(dict(BASE, actual_start=None), staff=STAFF, rows=[ROW])
_check("退勤だけの送信は422（end_without_start）", res.status_code == 422,
       str(res.status_code))
res, w, _ = _run(dict(BASE, actual_start="20:00", actual_end="19:00"), staff=STAFF)
_check("退勤<出勤は422（24時超表記の案内つき）", res.status_code == 422
       and "25:17" in str(res.json()), str(res.json()))
res, w, _ = _run(BASE, staff=None)
_check("未知のディーラー番号は404＋retry:false", res.status_code == 404
       and res.json()["detail"]["retry"] is False, str(res.json()))

print("\n[upsert（既存行の更新）]")
res, w, rv = _run(dict(BASE, actual_end=None), staff=STAFF, rows=[ROW])
upd = w[0][1]
_check("出勤のみ → checked_in・endはnull", res.json()["action"] == "updated"
       and upd["actual_start"] == "12:03" and upd["actual_end"] is None
       and upd["status"] == "checked_in", str(upd))
res, w, rv = _run(BASE, staff=STAFF, rows=[ROW])
upd = w[0][1]
_check("退勤つき → checked_out・25:17のまま保存", upd["actual_end"] == "25:17"
       and upd["status"] == "checked_out", str(upd))
_check("実績が変わったので支払い差し戻し", rv == 1, str(rv))
_check("9:30 は 09:30 に正規化される",
       _run(dict(BASE, actual_start="9:30", actual_end=None), staff=STAFF,
            rows=[ROW])[1][0][1]["actual_start"] == "09:30")

print("\n[null戻し（Q8: 打刻の取り消し）]")
done = dict(ROW, actual_start="12:03", actual_end="25:17", status="checked_out")
res, w, rv = _run(dict(BASE, actual_start=None, actual_end=None),
                  staff=STAFF, rows=[done])
upd = w[0][1]
_check("両方nullで scheduled へ戻る", upd["actual_start"] is None
       and upd["actual_end"] is None and upd["status"] == "scheduled", str(upd))
_check("戻し操作も支払い差し戻しが走る", rv == 1, str(rv))
res, w, rv = _run(dict(BASE, actual_start=None, actual_end=None),
                  staff=STAFF, rows=[])
_check("行が無い所への取り消しは skipped_noop（作成しない）",
       res.json()["action"] == "skipped_noop" and not w, str(res.json()))

print("\n[新規作成（シフト表に無い当日勤務）]")
res, w, rv = _run(dict(BASE, event_id=None), staff=STAFF, rows=[],
                  event={"id": 11, "start_date": "2026-08-12",
                         "end_date": "2026-08-16"})
ins = w[0][1]
_check("event_id省略でも日付から大会を解決して作成",
       res.json()["action"] == "created" and ins["event_id"] == 11, str(ins))
_check("予定が空にならない（支払い計算の対象に入る）",
       ins["planned_start"] == "12:03" and ins["planned_end"] == "25:17", str(ins))
res, w, rv = _run(dict(BASE, event_id=None), staff=STAFF, rows=[], event=None)
_check("該当大会なしは404", res.status_code == 404, str(res.status_code))

print("\n[順不同の再送（updated_at任意）]")
marked = dict(ROW, notes="〔API連携 key=k updated=2026-08-13T23:00:00+09:00〕")
res, w, rv = _run(dict(BASE, updated_at="2026-08-13T22:00:00+09:00"),
                  staff=STAFF, rows=[marked])
_check("古いupdated_atはskipped_stale（書き込みなし）",
       res.json()["action"] == "skipped_stale" and not w, str(res.json()))
res, w, rv = _run(dict(BASE, updated_at="2026-08-13T23:30:00+09:00",
                       attendance_key="p1-5-23-123"),
                  staff=STAFF, rows=[marked])
_check("新しいupdated_atは更新され、markerが置き換わる",
       res.json()["action"] == "updated"
       and "updated=2026-08-13T23:30:00+09:00" in w[0][1]["notes"],
       str(w[0][1].get("notes")))
res, w, rv = _run(BASE, staff=STAFF, rows=[marked])
_check("updated_at無し送信はガードせず最新扱いで更新（後方互換）",
       res.json()["action"] == "updated", str(res.json()))

print("\n[一意制約なしDBの重複行]")
dup2 = [dict(ROW), dict(ROW, id=10)]
res, w, rv = _run(BASE, staff=STAFF, rows=dup2)
_check("重複行があれば先頭を更新し warning を返す",
       res.json().get("warning") and len(w) == 1, str(res.json()))

print()
print("\n[CSV一括エンドポイント（2026-08-15 自動連動）]")
# 認証はミドルウェアが先行（本文なしでも401）
res = c.post("/api/attendance/csv", content=b"")
_check("CSV: 認証なしは401", res.status_code == 401, str(res.status_code))
res = c.post("/api/attendance/csv", content=b"", headers=_auth())
_check("CSV: 空ボディは422", res.status_code == 422, str(res.status_code))
_saved_evfn = m._event_for_date
m._event_for_date = lambda d: None
res = c.post("/api/attendance/csv", content="a,b\n1,2".encode(), headers=_auth())
_check("CSV: イベント未解決は404", res.status_code == 404, str(res.status_code))
m._event_for_date = _saved_evfn

# 取込本体はモック（画面アップロードと同一ロジックはtest36で担保済み）
import utils.attendance_csv as _acsv
_calls = []
def _fake_import(body, event_id, performed_by="", overwrite_manual=False):
    _calls.append({"event_id": event_id, "overwrite": overwrite_manual})
    return {"total": 2, "updated": ["NO.55 A太"], "created": [], "absent": [],
            "noop": 1, "unknown": [], "protected_diff": [], "invalid": [],
            "external": [], "kept_manual": ["NO.76 B子 保持"], "mix_only": [],
            "recalced": 1}
_orig_import = _acsv.import_attendance_csv
_acsv.import_attendance_csv = _fake_import
m._event_for_date = lambda d: {"id": 11}
try:
    _csv_body = ("dealer_number,date,actual_start,actual_end,is_absent\n"
                 "0055,2026-08-12,12:00,25:00,0\n").encode()
    res = c.post("/api/attendance/csv", content=_csv_body, headers=_auth())
    _check("CSV: 200・既定は手入力保護モード",
           res.status_code == 200 and res.json()["mode"] == "protect"
           and _calls[-1]["overwrite"] is False, str(res.json())[:120])
    _check("CSV: 日付からイベント解決", _calls[-1]["event_id"] == 11)
    _check("CSV: 保持リストを返す",
           res.json()["kept_manual"] == ["NO.76 B子 保持"])
    res = c.post("/api/attendance/csv?overwrite=1&event_id=11",
                 content=_csv_body, headers=_auth())
    _check("CSV: overwrite=1で上書きモード",
           res.json()["mode"] == "overwrite" and _calls[-1]["overwrite"] is True)
finally:
    _acsv.import_attendance_csv = _orig_import
    m._event_for_date = _saved_evfn

print("=" * 60)
if failures:
    print(f"❌ 失敗 {len(failures)}件: {failures}")
    sys.exit(1)
print("✅ 全テスト成功")
