"""勤怠CSV取込（utils/attendance_csv.py）の単体テスト — DB・ネットワーク非依存

TAKAツールCSV形式の契約を固定する:
  BOM可／必須列検査／冪等（同内容はno-op）／paid・approved保護／
  未登録NO・不正行（退勤のみ・逆転時刻・イベント外日付）の報告／
  行新規作成のstatus（退勤あり=checked_out・出勤のみ=checked_in・空=作らない）／
  欠勤化／影響者のバッチ再計算が1回呼ばれること
"""
from __future__ import annotations

import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

failures: list = []


def _check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + ("" if cond else f" — {detail}"))
    if not cond:
        failures.append(name)


# ============================================================
# フェイクdbモジュール（sys.modulesへ注入。attendance_csvは関数内importなので
# 呼び出し時にこちらが解決される）
# ============================================================
class FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self._op = None
        self._data = None
        self._filters = {}

    def update(self, data):
        self._op, self._data = "update", data
        return self

    def insert(self, data):
        self._op, self._data = "insert", data
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def execute(self):
        if self._op == "insert":
            self.store["inserted"].append(dict(self._data))
        elif self._op == "update":
            self.store["updated"].append(
                {"filters": dict(self._filters), "data": dict(self._data)})
        return types.SimpleNamespace(data=[])


class FakeClient:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeTable(self.store, name)


def make_fake_db(store):
    m = types.ModuleType("db")
    m.get_event_rates = lambda eid: [{"date": d} for d in
                                     ("2026-08-12", "2026-08-13")]
    m.get_all_staff = lambda: store["staff"]
    m.get_shifts_for_event = lambda eid: store["shifts"]
    m.get_payments_for_event = lambda eid: store["payments"]
    m.get_client = lambda: FakeClient(store)
    m.mark_absent = lambda sid: store["absented"].append(sid)
    m.reset_payment_to_pending = (
        lambda eid, sid, reason="": store["resets"].append(sid))
    m.log_action = lambda *a, **k: store["logs"].append((a, k))
    return m


def run_import(csv_text, store):
    fake = make_fake_db(store)
    saved_db = sys.modules.get("db")
    sys.modules["db"] = fake
    import utils.payment_recalc as pr
    saved_recalc = pr.recalc_staff_payments
    pr.recalc_staff_payments = (
        lambda eid, ids: store["recalc_calls"].append(list(ids)) or len(set(ids)))
    try:
        from utils.attendance_csv import import_attendance_csv
        return import_attendance_csv(csv_text.encode("utf-8-sig"), 11,
                                     performed_by="test")
    finally:
        pr.recalc_staff_payments = saved_recalc
        if saved_db is not None:
            sys.modules["db"] = saved_db
        else:
            sys.modules.pop("db", None)


def base_store():
    return {
        "staff": [
            {"id": 10, "no": 55, "name_jp": "A太"},
            {"id": 11, "no": 76, "name_jp": "B子"},
            {"id": 12, "no": 277, "name_jp": "よな"},
            {"id": 13, "no": 90, "name_jp": "C美"},
        ],
        "shifts": [
            {"id": 900, "staff_id": 10, "date": "2026-08-12",
             "actual_start": "12:00", "actual_end": "25:00", "status": "checked_out"},
            {"id": 901, "staff_id": 12, "date": "2026-08-12",
             "actual_start": None, "actual_end": None, "status": "absent"},
            {"id": 902, "staff_id": 13, "date": "2026-08-12",
             "actual_start": None, "actual_end": None, "status": "scheduled"},
        ],
        "payments": [
            {"staff_id": 10, "status": "pending", "total_amount": 1},
            {"staff_id": 12, "status": "paid", "total_amount": 9000},
            {"staff_id": 13, "status": "pending", "total_amount": 0},
        ],
        "inserted": [], "updated": [], "absented": [], "resets": [],
        "logs": [], "recalc_calls": [],
    }


print("[A] 形式・ヘッダ")
try:
    run_import("foo,bar\n1,2", base_store())
    _check("必須列不足でValueError", False)
except ValueError:
    _check("必須列不足でValueError", True)
try:
    run_import("dealer_number,date,actual_start,actual_end,is_absent\n", base_store())
    _check("データ行なしでValueError", False)
except ValueError:
    _check("データ行なしでValueError", True)

print("[B] 冪等・保護・不正行")
st = base_store()
rep = run_import(
    "dealer_number,date,actual_start,actual_end,is_absent\n"
    "0055,2026-08-12,12:00,25:00,0\n"      # 既に一致 → noop
    "0277,2026-08-12,10:00,15:00,0\n"      # paid → 保護差分
    "0999,2026-08-12,10:00,15:00,0\n"      # 未登録
    "0076,2026-08-12,,15:00,0\n"           # 退勤のみ → 不正
    "0076,2026-08-12,18:00,15:00,0\n"      # 逆転 → 不正
    "0076,2026-08-11,10:00,15:00,0\n"      # イベント外日付 → 不正
    "0076,2026-08-12,10:00,49:00,0\n",     # 48h超 → 不正
    st)
_check("一致はno-op", rep["noop"] == 1, str(rep["noop"]))
_check("paidは保護差分", len(rep["protected_diff"]) == 1 and "よな" in rep["protected_diff"][0])
_check("未登録NOを報告", rep["unknown"] == ["NO.999"], str(rep["unknown"]))
_check("不正行4種を報告", len(rep["invalid"]) == 4, str(rep["invalid"]))
_check("書き込みなし", not st["updated"] and not st["inserted"])
_check("監査ログ1件", len(st["logs"]) == 1)

print("[C] 更新・新規作成・欠勤・再計算バッチ")
st = base_store()
rep = run_import(
    "dealer_number,date,actual_start,actual_end,is_absent\n"
    "0055,2026-08-12,12:00,26:30,0\n"      # 更新（延長）
    "0076,2026-08-12,20:00,29:00,0\n"      # 行なし → 新規 checked_out
    "0076,2026-08-13,20:00,,0\n"           # 行なし・出勤のみ → 新規 checked_in
    "0090,2026-08-12,,,1\n",               # 欠勤化
    st)
_check("更新1件", len(rep["updated"]) == 1 and st["updated"][0]["data"]["actual_end"] == "26:30")
_check("新規2件", len(rep["created"]) == 2, str(rep["created"]))
_ins = {(i["date"], i["status"]): i for i in st["inserted"]}
_check("退勤ありの新規=checked_out",
       ("2026-08-12", "checked_out") in _ins)
_check("出勤のみの新規=checked_in（QA修正）",
       ("2026-08-13", "checked_in") in _ins
       and _ins[("2026-08-13", "checked_in")]["actual_end"] is None)
_check("欠勤化1件", rep["absent"] == ["NO.90 C美"] and st["absented"] == [902])
_check("更新分は差し戻し済み", 10 in st["resets"])
_check("バッチ再計算は1回だけ", len(st["recalc_calls"]) == 1, str(st["recalc_calls"]))
_check("再計算対象=更新1+新規2（欠勤はフック側）",
       sorted(set(st["recalc_calls"][0])) == [10, 11], str(st["recalc_calls"]))
_check("recalced数を報告", rep["recalced"] == 2, str(rep.get("recalced")))

print("[D] 空行（出勤なし・欠勤でもない）は行を作らない")
st = base_store()
rep = run_import(
    "dealer_number,date,actual_start,actual_end,is_absent\n"
    "0076,2026-08-12,,,0\n", st)
_check("空行はno-op扱い・insertなし", rep["noop"] == 1 and not st["inserted"])

print("=" * 60)
if failures:
    print(f"❌ 失敗 {len(failures)}件:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✅ 全テスト成功")
