"""テスト用のDBスタブ（2026-08-02 追加）

目的:
    UIテスト（21_ui_elements_test.py 等）を**本番DBに接続せずに**走らせる。

背景:
    db.py から既定のDBキーを削除（漏洩対策）した結果、環境変数が無い環境では
    ページがDB呼び出しで例外を出すようになり、UIテストが全滅していた。
    テストのたびに本番へ接続するのは、
      ・テストが本番データを汚す
      ・CIに本番の鍵を置く必要が出る
      ・DBが落ちているとテストも落ちる（テストの意味が変わる）
    という3点で望ましくない。

方針:
    db.get_client() だけを差し替える。db.py の各関数（集計・整形・状態遷移）は
    本物がそのまま動くので、「DBの応答をどう扱うか」のロジックは実際に検証される。
    返却データは既定で空。必要なテストは seed() で任意の行を仕込める。

使い方:
    from _fake_db import install_fake_db
    install_fake_db()                      # 以降 db.* は空のDBとして動く
    install_fake_db({"p1_events": [...]})  # 特定テーブルに行を仕込む
"""

from __future__ import annotations

from typing import Any


class _Result:
    def __init__(self, data: list):
        self.data = data
        self.count = len(data)


class _Query:
    """supabase-py のクエリビルダを模した最小実装。

    実装しているのは本アプリが実際に使うメソッドのみ。
    未対応メソッドを呼ばれたら AttributeError で気づけるよう、あえて広く受けない。
    """

    def __init__(self, rows: list, op: str = "select"):
        self._rows = list(rows)
        self._op = op
        self._filters: list[tuple] = []

    # --- 絞り込み ---
    def eq(self, col: str, val: Any):
        self._filters.append(("eq", col, val))
        return self

    def neq(self, col: str, val: Any):
        self._filters.append(("neq", col, val))
        return self

    def in_(self, col: str, vals: list):
        self._filters.append(("in", col, list(vals)))
        return self

    def gte(self, col: str, val: Any):
        self._filters.append(("gte", col, val))
        return self

    def lte(self, col: str, val: Any):
        self._filters.append(("lte", col, val))
        return self

    def like(self, col: str, val: Any):
        self._filters.append(("like", col, val))
        return self

    # --- 整形（テストでは順序・件数の正しさまでは見ない） ---
    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        return self

    def execute(self) -> _Result:
        if self._op != "select":
            # 書き込み系は「1件処理した」体で返す（呼び出し側の分岐を成立させる）
            return _Result([{"id": 1}])
        rows = self._rows
        for kind, col, val in self._filters:
            if kind == "eq":
                rows = [r for r in rows if r.get(col) == val]
            elif kind == "neq":
                rows = [r for r in rows if r.get(col) != val]
            elif kind == "in":
                rows = [r for r in rows if r.get(col) in val]
        return _Result(rows)


class _Table:
    def __init__(self, rows: list):
        self._rows = rows

    def select(self, *a, **k):
        return _Query(self._rows, "select")

    def insert(self, payload, **k):
        return _Query(self._rows, "insert")

    def update(self, payload, **k):
        return _Query(self._rows, "update")

    def upsert(self, payload, **k):
        return _Query(self._rows, "upsert")

    def delete(self, **k):
        return _Query(self._rows, "delete")


class FakeClient:
    def __init__(self, seed: dict | None = None):
        self._seed = dict(seed or {})

    def table(self, name: str) -> _Table:
        return _Table(self._seed.get(name, []))

    # Storage を使う画面（領収書・契約書）向けの最小スタブ
    @property
    def storage(self):
        return self

    def from_(self, bucket: str):
        return self

    def upload(self, *a, **k):
        return {"path": "dummy"}

    def download(self, *a, **k):
        return b"%PDF-1.4 dummy"

    def create_signed_url(self, *a, **k):
        return {"signedURL": "https://example.invalid/dummy"}


def install_fake_db(seed: dict | None = None) -> FakeClient:
    """db.get_client() を差し替える。既に差し替え済みなら seed だけ更新する。"""
    import db as _db

    client = FakeClient(seed)
    _db.get_client = lambda: client  # type: ignore[assignment]

    # db_schema.has_column は実DBを見に行くのでテストでは常に True にする
    try:
        from utils import db_schema
        db_schema.has_column = lambda table, col: True  # type: ignore[assignment]
    except Exception:
        pass

    return client
