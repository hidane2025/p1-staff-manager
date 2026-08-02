"""P1 Staff Manager — 支払いの内部統制 回帰テスト（2026-08-02 追加）

QAで確定した db.py の欠陥を再現し、修正後に二度と戻らないよう固定する。

対象: db.save_payment / db.reset_payment_to_pending /
      db.set_payment_adjustment / db.approve_payment / db.mark_paid

再現する欠陥（現状のコードでは [A][B] が失敗する = 赤になるのが正しい）:
  [A] save_payment が status='approved' の支払いを再承認なしで上書きする
      （db.py:1206-1248）。金額だけ書き換わり status は approved のまま、
      approved_by / approved_at も残る。
      正しくは「金額が変わるなら pending に戻し、承認情報をクリア」。
      比較対象: recompute_payable_for_event は db.py:1350-1356 で実際にそうしている。
  [B] save_payment が金額変更時に領収書（receipt_received / receipt_pdf_path /
      receipt_token / receipt_token_expires_at）を無効化しない（db.py:1214-1233）。
      set_payment_adjustment（db.py:1288-1295）は同じ状況でクリアしている＝
      save_payment だけが統制から漏れている。
  [C] 参考として「正しく動いている統制」も固定する（回帰防止）。
      現状でも通るべきもの＝ここが赤になったら統制が壊れた合図。

DB接続:
    本番DBには一切繋がない。test_e2e/_fake_db.py の install_fake_db() で
    db.get_client() を差し替え、さらに書き込みを検証できるよう
    RecordingClient（FakeClient のサブクラス）へ置き換える。
    FakeClient は update/insert が常に成功を返すため、
    「status 述語で弾かれたか」「payload に何を書いたか」を検証できない。
    RecordingClient は .eq/.neq をシード行に適用して実際に書き換えるので、
    DB側の原子的更新（.eq("status","pending") 等）まで再現できる。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/31_payment_control_regression_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fake_db import FakeClient, install_fake_db  # noqa: E402

import db  # noqa: E402


PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    mark = PASS if cond else FAIL
    print(f"  {mark} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


# ============================================================
# 0. 検証用DBスタブ（書き込みを記録し、絞り込み条件を実際に適用する）
# ============================================================

class _Result:
    def __init__(self, data: list):
        self.data = data
        self.count = len(data)


class _RecQuery:
    """supabase-py のクエリビルダ模写。update/insert を seed 行へ実適用する。

    _fake_db._Query との違いは 2点だけ:
      1. update / insert / delete でも絞り込み条件を評価し、
         条件に合った行「だけ」を書き換える（0件なら data=[] を返す）。
         → db.py の TOCTOU 対策 `.eq("status","pending")` `.neq("status","paid")`
           が効いているかを検証できる。
      2. 渡された payload を log に記録する（何を書いたかの検証用）。
    """

    def __init__(self, rows: list, op: str, payload=None, log: list | None = None,
                 table: str = ""):
        self._rows = rows          # seed のリスト実体を共有（更新を可視化するため）
        self._op = op
        self._payload = dict(payload) if isinstance(payload, dict) else payload
        self._filters: list[tuple] = []
        self._log = log if log is not None else []
        self._table = table

    # --- 絞り込み ---
    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self._filters.append(("neq", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def lte(self, col, val):
        self._filters.append(("lte", col, val))
        return self

    def like(self, col, val):
        self._filters.append(("like", col, val))
        return self

    # --- 整形（本テストでは順序・件数は見ない） ---
    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        return self

    def _match(self, r: dict) -> bool:
        for kind, col, val in self._filters:
            cur = r.get(col)
            if kind == "eq" and cur != val:
                return False
            if kind == "neq" and cur == val:
                return False
            if kind == "in" and cur not in val:
                return False
            if kind == "gte" and not (cur is not None and cur >= val):
                return False
            if kind == "lte" and not (cur is not None and cur <= val):
                return False
        return True

    def execute(self) -> _Result:
        if self._op == "select":
            return _Result([r for r in self._rows if self._match(r)])

        if self._op == "insert":
            row = dict(self._payload or {})
            row.setdefault("id", len(self._rows) + 1)
            self._rows.append(row)
            self._log.append({"table": self._table, "op": "insert",
                              "payload": dict(row), "matched": 1})
            return _Result([row])

        if self._op in ("update", "upsert"):
            matched = [r for r in self._rows if self._match(r)]
            for r in matched:
                r.update(self._payload or {})
            self._log.append({"table": self._table, "op": "update",
                              "payload": dict(self._payload or {}),
                              "filters": list(self._filters),
                              "matched": len(matched)})
            return _Result(matched)

        if self._op == "delete":
            matched = [r for r in self._rows if self._match(r)]
            for r in matched:
                self._rows.remove(r)
            self._log.append({"table": self._table, "op": "delete",
                              "filters": list(self._filters),
                              "matched": len(matched)})
            return _Result(matched)

        return _Result([])


class _RecTable:
    def __init__(self, rows: list, log: list, name: str):
        self._rows, self._log, self._name = rows, log, name

    def select(self, *a, **k):
        return _RecQuery(self._rows, "select", log=self._log, table=self._name)

    def insert(self, payload, **k):
        return _RecQuery(self._rows, "insert", payload, self._log, self._name)

    def update(self, payload, **k):
        return _RecQuery(self._rows, "update", payload, self._log, self._name)

    def upsert(self, payload, **k):
        return _RecQuery(self._rows, "upsert", payload, self._log, self._name)

    def delete(self, **k):
        return _RecQuery(self._rows, "delete", log=self._log, table=self._name)


class RecordingClient(FakeClient):
    """FakeClient のサブクラス。書き込み payload を self.writes に記録する。"""

    def __init__(self, seed: dict | None = None):
        super().__init__(seed)
        self.writes: list = []

    def table(self, name: str) -> _RecTable:
        # setdefault でリスト実体を固定する（insert/update をまたいで状態が残る）
        rows = self._seed.setdefault(name, [])
        return _RecTable(rows, self.writes, name)


def _install(seed: dict) -> RecordingClient:
    """db.get_client() を RecordingClient に差し替える（本番DBには繋がない）。"""
    install_fake_db(seed)            # db_schema.has_column を常に True にする副作用も使う
    client = RecordingClient(seed)
    db.get_client = lambda: client   # type: ignore[assignment]
    return client


def _payment(**over) -> dict:
    """支払い1行のひな型。

    金額の根拠（時給1,500円・深夜割増1.25倍のP1標準運用に合わせた実データ相当）:
        base_pay 20,000（1,500円 × 13.33h 相当の丸め値）
        night_pay 1,875（1,500 × 1.25 × 1h）
        transport_total 1,250
        → total_amount = 20,000 + 1,875 + 1,250 = 23,125
    """
    row = {
        "id": 1, "event_id": 1, "staff_id": 10,
        "status": "pending",
        "base_pay": 20000, "night_pay": 1875, "transport_total": 1250,
        "floor_bonus_total": 0, "mix_bonus_total": 0, "attendance_bonus": 0,
        "break_deduction": 0, "adjustment": 0, "adjustment_note": "",
        "total_amount": 23125, "payable_amount": 23125,
        "approved_by": None, "approved_at": None,
        "receipt_received": 0, "receipt_pdf_path": None,
        "receipt_token": None, "receipt_token_expires_at": None,
        "notes": "",
    }
    row.update(over)
    return row


def _save_23125(event_id=1, staff_id=10):
    """変更前と同額（23,125円）で save_payment を呼ぶ。"""
    db.save_payment(event_id, staff_id,
                    base_pay=20000, night_pay=1875, transport_total=1250,
                    floor_bonus_total=0, mix_bonus_total=0, attendance_bonus=0,
                    total_amount=23125)


def _save_25000(event_id=1, staff_id=10):
    """金額が変わるケース。base_pay を 21,875 に上げて再計算した想定。

    21,875 + 1,875 + 1,250 = 25,000（旧 23,125 から +1,875円）。
    """
    db.save_payment(event_id, staff_id,
                    base_pay=21875, night_pay=1875, transport_total=1250,
                    floor_bonus_total=0, mix_bonus_total=0, attendance_bonus=0,
                    total_amount=25000)


# 端数処理なし（rounding_unit=0）＝ payable_amount は total_amount と同額になる
_EVENT_NO_ROUND = {"id": 1, "name": "P1 GRANDPRIX 名古屋", "rounding_unit": 0}
# 端数処理 1,000円単位。round_amount は切り上げなので 23,125 → 24,000
_EVENT_ROUND_1000 = {"id": 2, "name": "P1 GRANDPRIX 大阪", "rounding_unit": 1000}


# ============================================================
# 1. [欠陥A] save_payment が承認済み(approved)を再承認なしで上書きする
# ============================================================
print("\n[1] 欠陥A: save_payment は金額を変えたら承認を差し戻すべき")

seed = {"p1_events": [dict(_EVENT_NO_ROUND)],
        "p1_payments": [_payment(status="approved", total_amount=23125,
                                 payable_amount=23125,
                                 approved_by="ooishi@p1", approved_at="2026-08-01 10:00:00")],
        "p1_audit_log": []}
_install(seed)
_save_25000()
row = seed["p1_payments"][0]

# まず「金額は実際に書き換わった」ことを確認する（＝上書き自体は起きている）。
# ここが通ったうえで status が approved のままなら、無承認で支払額が変わったことになる。
_check("前提: 金額が 23,125 → 25,000 に上書きされる",
       row["total_amount"] == 25000, f"got {row['total_amount']}")
_check("前提: payable_amount も 25,000 に追随（rounding_unit=0 なので同額）",
       row["payable_amount"] == 25000, f"got {row['payable_amount']}")

# 本命。recompute_payable_for_event（db.py:1350-1356）は
# 「approved の金額が変わったら pending へ差し戻し、承認情報を消す」を実装している。
# save_payment だけ同じ統制が無く、承認済みの金額が無承認で書き換わる。
_check("金額が変わったら status は pending に戻る",
       row["status"] == "pending", f"got {row['status']}（承認済みのまま金額だけ変わった）")
_check("金額が変わったら approved_by はクリアされる",
       row["approved_by"] is None, f"got {row['approved_by']}（旧承認者が残っている）")
_check("金額が変わったら approved_at はクリアされる",
       row["approved_at"] is None, f"got {row['approved_at']}（旧承認日時が残っている）")

# 過剰修正の防止: 同額の再計算（シフト無変更で再実行など）では差し戻さない。
# 差し戻すと現場が毎回承認し直すことになり、承認が形骸化する。
seed2 = {"p1_events": [dict(_EVENT_NO_ROUND)],
         "p1_payments": [_payment(status="approved", total_amount=23125,
                                  payable_amount=23125,
                                  approved_by="ooishi@p1", approved_at="2026-08-01 10:00:00")],
         "p1_audit_log": []}
_install(seed2)
_save_23125()
row2 = seed2["p1_payments"][0]
_check("同額の再計算では approved のまま（不要な差し戻しをしない）",
       row2["status"] == "approved" and row2["approved_by"] == "ooishi@p1",
       f"status={row2['status']} approved_by={row2['approved_by']}")

# 端数処理ありのイベントでも payable_amount が正しく算出されること（計算根拠の固定）。
# round_amount は切り上げ: 23,125 % 1000 = 125 ≠ 0 → (23 + 1) × 1000 = 24,000
seed3 = {"p1_events": [dict(_EVENT_ROUND_1000)],
         "p1_payments": [], "p1_audit_log": []}
_install(seed3)
db.save_payment(2, 10, base_pay=20000, night_pay=1875, transport_total=1250,
                floor_bonus_total=0, mix_bonus_total=0, attendance_bonus=0,
                total_amount=23125)
row3 = seed3["p1_payments"][0]
_check("新規作成: rounding_unit=1000 で payable_amount = 24,000（23,125を切り上げ）",
       row3["payable_amount"] == 24000, f"got {row3.get('payable_amount')}")
_check("新規作成: status は指定しない＝DB既定の pending 運用（statusを書かない）",
       "status" not in row3 or row3["status"] == "pending",
       f"got {row3.get('status')}")


# ============================================================
# 2. [欠陥B] save_payment が金額変更時に領収書を無効化しない
# ============================================================
print("\n[2] 欠陥B: save_payment は金額を変えたら発行済み領収書を無効化すべき")

seed = {"p1_events": [dict(_EVENT_NO_ROUND)],
        "p1_payments": [_payment(status="pending", total_amount=23125,
                                 payable_amount=23125,
                                 receipt_received=1,
                                 receipt_pdf_path="receipts/2026/ev1_staff10.pdf",
                                 receipt_token="tok_abc123",
                                 receipt_token_expires_at="2026-08-09 10:00:00")],
        "p1_audit_log": []}
_install(seed)
_save_25000()
row = seed["p1_payments"][0]

_check("前提: 金額が 23,125 → 25,000 に上書きされる",
       row["total_amount"] == 25000, f"got {row['total_amount']}")

# 旧額23,125円の領収書PDFとトークンが残ると、
# ①スタッフに旧額の領収書が再ダウンロードされる ②受領フラグが立ったまま
# 支払いゲートを通過する、の二重事故になる。
_check("金額が変わったら receipt_received は 0 に戻る",
       row["receipt_received"] == 0,
       f"got {row['receipt_received']}（旧額の受領フラグが立ったまま）")
_check("金額が変わったら receipt_pdf_path は None になる",
       row["receipt_pdf_path"] is None,
       f"got {row['receipt_pdf_path']}（旧額23,125円のPDFが残っている）")
_check("金額が変わったら receipt_token は None になる",
       row["receipt_token"] is None,
       f"got {row['receipt_token']}（旧額の領収書URLが有効なまま）")
_check("金額が変わったら receipt_token_expires_at は None になる",
       row["receipt_token_expires_at"] is None,
       f"got {row['receipt_token_expires_at']}")

# 同額なら無効化しない（再発行の手間を無駄に増やさない）
seed = {"p1_events": [dict(_EVENT_NO_ROUND)],
        "p1_payments": [_payment(status="pending", total_amount=23125,
                                 payable_amount=23125,
                                 receipt_received=1,
                                 receipt_pdf_path="receipts/2026/ev1_staff10.pdf",
                                 receipt_token="tok_abc123")],
        "p1_audit_log": []}
_install(seed)
_save_23125()
row = seed["p1_payments"][0]
_check("同額の再計算では領収書を無効化しない",
       row["receipt_received"] == 1 and row["receipt_pdf_path"] is not None,
       f"received={row['receipt_received']} path={row['receipt_pdf_path']}")


# ============================================================
# 3. [比較] set_payment_adjustment は同じ状況で正しく無効化している
#    → save_payment だけが統制から漏れている証拠。ここは現状でも通るべき。
# ============================================================
print("\n[3] 比較: set_payment_adjustment は領収書を無効化できている")

seed = {"p1_events": [dict(_EVENT_NO_ROUND)],
        "p1_payments": [_payment(id=5, status="pending",
                                 total_amount=23125, adjustment=0,
                                 payable_amount=23125,
                                 receipt_received=1,
                                 receipt_pdf_path="receipts/2026/ev1_staff10.pdf",
                                 receipt_token="tok_abc123",
                                 receipt_token_expires_at="2026-08-09 10:00:00")],
        "p1_audit_log": []}
_install(seed)
# 新 total = (旧 total 23,125 − 旧 adjustment 0) + 新 adjustment 1,875 = 25,000
ok = db.set_payment_adjustment(5, 1875, "深夜対応の臨時手当", event_id=1)
row = seed["p1_payments"][0]
_check("set_payment_adjustment は True を返す", ok is True, f"got {ok}")
_check("合計 = (23,125 − 0) + 1,875 = 25,000",
       row["total_amount"] == 25000, f"got {row['total_amount']}")
_check("set_payment_adjustment: receipt_received を 0 に戻している",
       row["receipt_received"] == 0, f"got {row['receipt_received']}")
_check("set_payment_adjustment: receipt_pdf_path / receipt_token を消している",
       row["receipt_pdf_path"] is None and row["receipt_token"] is None,
       f"path={row['receipt_pdf_path']} token={row['receipt_token']}")

# 金額が変わらない調整（同じ値の再保存）では無効化しない
seed = {"p1_events": [dict(_EVENT_NO_ROUND)],
        "p1_payments": [_payment(id=5, status="pending",
                                 total_amount=25000, adjustment=1875,
                                 payable_amount=25000,
                                 receipt_received=1,
                                 receipt_pdf_path="receipts/2026/ev1_staff10.pdf",
                                 receipt_token="tok_abc123")],
        "p1_audit_log": []}
_install(seed)
db.set_payment_adjustment(5, 1875, "深夜対応の臨時手当", event_id=1)
row = seed["p1_payments"][0]
# 新 total = (25,000 − 1,875) + 1,875 = 25,000 ＝ 変化なし
_check("同額なら set_payment_adjustment も領収書を残す",
       row["receipt_received"] == 1 and row["receipt_token"] == "tok_abc123",
       f"received={row['receipt_received']} token={row['receipt_token']}")

# 承認済み(approved)の臨時調整はブロック（再承認を経るべき）
seed = {"p1_events": [dict(_EVENT_NO_ROUND)],
        "p1_payments": [_payment(id=5, status="approved", total_amount=23125,
                                 approved_by="ooishi@p1")],
        "p1_audit_log": []}
_install(seed)
blocked = db.set_payment_adjustment(5, 1875, "承認後の調整", event_id=1)
row = seed["p1_payments"][0]
_check("承認済みの臨時調整は False で拒否される", blocked is False, f"got {blocked}")
_check("承認済みの金額は書き換わらない（23,125のまま）",
       row["total_amount"] == 23125, f"got {row['total_amount']}")


# ============================================================
# 4. [C] 正しく動いている統制の固定（回帰防止）
# ============================================================
print("\n[4] 回帰防止: 支払済み(paid)の保護")

seed = {"p1_events": [dict(_EVENT_NO_ROUND)],
        "p1_payments": [_payment(status="paid", total_amount=23125,
                                 payable_amount=23125,
                                 approved_by="ooishi@p1", approved_at="2026-08-01 10:00:00")],
        "p1_audit_log": []}
_install(seed)
db.save_payment(1, 10, base_pay=99999, night_pay=0, transport_total=0,
                floor_bonus_total=0, mix_bonus_total=0, attendance_bonus=0,
                total_amount=99999)
row = seed["p1_payments"][0]
_check("save_payment は支払済みを上書きしない（23,125のまま）",
       row["total_amount"] == 23125, f"got {row['total_amount']}")
_check("save_payment 後も status は paid のまま",
       row["status"] == "paid", f"got {row['status']}")

# reset_payment_to_pending: paid は保護
seed = {"p1_events": [dict(_EVENT_NO_ROUND)],
        "p1_payments": [_payment(status="paid", approved_by="ooishi@p1")],
        "p1_audit_log": []}
_install(seed)
res = db.reset_payment_to_pending(1, 10, reason="凍結再計算")
row = seed["p1_payments"][0]
_check("reset_payment_to_pending は支払済みに対して False を返す",
       res is False, f"got {res}")
_check("reset_payment_to_pending 後も status は paid のまま",
       row["status"] == "paid", f"got {row['status']}")

# reset_payment_to_pending: approved は差し戻せる
seed = {"p1_events": [dict(_EVENT_NO_ROUND)],
        "p1_payments": [_payment(status="approved", approved_by="ooishi@p1",
                                 approved_at="2026-08-01 10:00:00")],
        "p1_audit_log": []}
_install(seed)
res = db.reset_payment_to_pending(1, 10, reason="凍結再計算")
row = seed["p1_payments"][0]
_check("reset_payment_to_pending は承認済みを True で差し戻す", res is True, f"got {res}")
_check("差し戻し後 status=pending / approved_by・approved_at が None",
       row["status"] == "pending" and row["approved_by"] is None
       and row["approved_at"] is None,
       f"status={row['status']} by={row['approved_by']} at={row['approved_at']}")

# 存在しないスタッフは False（例外を投げない）
seed = {"p1_events": [dict(_EVENT_NO_ROUND)], "p1_payments": [], "p1_audit_log": []}
_install(seed)
_check("支払いレコードが無ければ reset は False",
       db.reset_payment_to_pending(1, 999) is False)


print("\n[5] 回帰防止: 状態遷移は pending → approved → paid の一方向")

def _one_row(status: str, **over):
    seed = {"p1_events": [dict(_EVENT_NO_ROUND)],
            "p1_payments": [_payment(id=7, status=status, **over)],
            "p1_audit_log": []}
    _install(seed)
    return seed["p1_payments"][0]

# pending → approved は許可
row = _one_row("pending")
_check("pending → approved は True", db.approve_payment(7, "ooishi@p1", 1) is True)
_check("承認後 status=approved / approved_by が記録される",
       row["status"] == "approved" and row["approved_by"] == "ooishi@p1",
       f"status={row['status']} by={row['approved_by']}")

# approved の二重承認は不可（.eq("status","pending") で弾かれる）
row = _one_row("approved", approved_by="ooishi@p1")
_check("approved の再承認は False（二重承認を弾く）",
       db.approve_payment(7, "nakano@p1", 1) is False)
_check("再承認の試行で approved_by は書き換わらない",
       row["approved_by"] == "ooishi@p1", f"got {row['approved_by']}")

# paid → approved の逆行は不可
row = _one_row("paid")
_check("paid を approve しようとしても False（逆行不可）",
       db.approve_payment(7, "nakano@p1", 1) is False)
_check("逆行の試行後も status は paid のまま",
       row["status"] == "paid", f"got {row['status']}")

# pending → paid の承認スキップは不可
row = _one_row("pending")
_check("pending を直接 paid にできない（承認スキップ不可）",
       db.mark_paid(7, 1, performed_by="nakano@p1") is False)
_check("承認スキップ試行後も status は pending のまま",
       row["status"] == "pending", f"got {row['status']}")

# approved → paid は許可
row = _one_row("approved", approved_by="ooishi@p1")
_check("approved → paid は True",
       db.mark_paid(7, 1, performed_by="nakano@p1") is True)
_check("支払後 status=paid / paid_by に実行者が残る",
       row["status"] == "paid" and row.get("paid_by") == "nakano@p1",
       f"status={row['status']} paid_by={row.get('paid_by')}")

# paid の二重支払は不可
row = _one_row("paid", paid_by="nakano@p1")
_check("paid の再支払は False（二重支払を弾く）",
       db.mark_paid(7, 1, performed_by="ooishi@p1") is False)
_check("二重支払の試行で paid_by は書き換わらない",
       row.get("paid_by") == "nakano@p1", f"got {row.get('paid_by')}")


# ============================================================
# 6. [比較] recompute_payable_for_event は承認差し戻しを実装している
#    save_payment に同じ統制が無いことの対比。ここは現状でも通るべき。
# ============================================================
print("\n[6] 比較: recompute_payable_for_event は approved を差し戻す")

# 端数処理を 0 → 1000 に変更した想定。23,125 → 切り上げ 24,000 で確定額が変わる。
seed = {"p1_events": [dict(_EVENT_ROUND_1000)],
        "p1_payments": [_payment(id=9, event_id=2, status="approved",
                                 total_amount=23125, payable_amount=23125,
                                 approved_by="ooishi@p1",
                                 approved_at="2026-08-01 10:00:00",
                                 receipt_received=1,
                                 receipt_pdf_path="receipts/2026/ev2_staff10.pdf",
                                 receipt_token="tok_xyz789")],
        "p1_audit_log": []}
_install(seed)
out = db.recompute_payable_for_event(2, rounding_unit=1000)
row = seed["p1_payments"][0]
_check("payable_amount = 24,000（23,125を1,000単位で切り上げ）",
       row["payable_amount"] == 24000, f"got {row['payable_amount']}")
_check("recompute: 確定額が変わったら status を pending に差し戻す",
       row["status"] == "pending", f"got {row['status']}")
_check("recompute: approved_by / approved_at をクリアする",
       row["approved_by"] is None and row["approved_at"] is None,
       f"by={row['approved_by']} at={row['approved_at']}")
_check("recompute: 旧領収書（PDF/トークン/受領フラグ）を無効化する",
       row["receipt_pdf_path"] is None and row["receipt_token"] is None
       and row["receipt_received"] == 0,
       f"path={row['receipt_pdf_path']} token={row['receipt_token']} "
       f"received={row['receipt_received']}")
_check("recompute: 集計は updated=1 / invalidated=1 / reverted=1",
       isinstance(out, dict) and out.get("updated") == 1
       and out.get("invalidated") == 1 and out.get("reverted") == 1,
       f"got {out}")

# paid は recompute でも触らない
seed = {"p1_events": [dict(_EVENT_ROUND_1000)],
        "p1_payments": [_payment(id=9, event_id=2, status="paid",
                                 total_amount=23125, payable_amount=23125)],
        "p1_audit_log": []}
_install(seed)
out = db.recompute_payable_for_event(2, rounding_unit=1000)
row = seed["p1_payments"][0]
_check("recompute: paid は payable_amount も status も変えない",
       row["payable_amount"] == 23125 and row["status"] == "paid",
       f"payable={row['payable_amount']} status={row['status']}")


# ============================================================
# 結果集計
# ============================================================
print()
print("=" * 60)
if failures:
    print(f"{FAIL} 失敗 {len(failures)}件:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"{PASS} 全テスト成功")
    sys.exit(0)
