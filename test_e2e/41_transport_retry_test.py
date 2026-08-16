"""接続断（Server disconnected）の自動リトライ 回帰テスト（2026-08-16 追加）

再現した事故:
    支払い計算ページを開くと画面いっぱいに
    httpx.RemoteProtocolError: Server disconnected のトレースバックが出て操作不能
    （2026-08-16 中野さん報告・NO.344 かずちゃま を表示中）。

    原因は「送信そのものが落ちる転送例外」が誰にも捕まらないこと。
    dbx.core.get_client は st.cache_resource で永続キャッシュされ、中の httpx が
    keep-alive 接続を使い回す。Supabase側は待機中の接続を一定時間で切るため、
    次に使うと送信先が既に閉じている。postgrest の send_with_retry は
    **HTTPステータス 503/520 しか見ておらず**、転送例外は素通しする。

固定する仕様:
  [A] 転送例外（RemoteProtocolError等）は自動で張り直す（読み取りが落ちない）。
  [B] POST（insert）は再送しない —— 二重登録を作らないための線引き。
      サーバが処理し終えてから接続が切れた場合、再送すると同じ行が2件入る。
  [C] 何度やっても駄目なら最後は例外を上げる（無限ループにしない）。
  [D] 転送例外でない失敗（APIError等）はそのまま素通しする（握り潰さない）。

DB接続:
    本番DBには繋がない。postgrest の送信関数を偽物に差し替えて回数だけ数える。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/41_transport_retry_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
from postgrest._sync import request_builder as rb  # noqa: E402

from dbx import core  # noqa: E402

PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    print(f"  {PASS if cond else FAIL} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


class _Req:
    """postgrest の RequestConfig の代役（リトライ判定に使う属性だけ持つ）。"""

    def __init__(self, method: str):
        self.http_method = method


def _install(fail_times: int, exc):
    """fail_times 回だけ exc を投げ、その後 "OK" を返す送信関数を仕込む。

    dbx.core は元の送信関数を包むので、先に素の実装を差し替えてから
    パッチを当て直す（テスト間で二重に包まれないようフラグも戻す）。
    """
    calls = {"n": 0}

    def _fake(req):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise exc
        return "OK"

    rb.send_with_retry = _fake
    core._transport_retry_installed = False
    core._install_transport_retry()
    return calls


_DISCONNECT = httpx.RemoteProtocolError("Server disconnected")

print("\n[A] 接続断は自動で張り直す")
calls = _install(1, _DISCONNECT)
res = rb.send_with_retry(_Req("GET"))
_check("GET: 1回切れても成功する", res == "OK", f"res={res}")
_check("GET: 2回試行している", calls["n"] == 2, f"試行={calls['n']}")

calls = _install(2, _DISCONNECT)
res = rb.send_with_retry(_Req("GET"))
_check("GET: 2回切れても3回目で成功する", res == "OK", f"res={res}")

for _m in ("PATCH", "DELETE"):
    calls = _install(1, _DISCONNECT)
    res = rb.send_with_retry(_Req(_m))
    _check(f"{_m}: 同じ結果になる操作は再送する", res == "OK", f"res={res}")

print("\n[B] POST（insert）は二重登録を避けるため再送しない")
calls = _install(1, _DISCONNECT)
try:
    rb.send_with_retry(_Req("POST"))
    _check("POST: 例外がそのまま上がる", False, "例外が出なかった")
except httpx.RemoteProtocolError:
    _check("POST: 例外がそのまま上がる", True)
_check("POST: 1回しか送っていない", calls["n"] == 1, f"試行={calls['n']}")

print("\n[C] 復旧しなければ諦めて例外を上げる（無限ループにしない）")
calls = _install(99, _DISCONNECT)
try:
    rb.send_with_retry(_Req("GET"))
    _check("GET: 上限に達したら例外", False, "例外が出なかった")
except httpx.RemoteProtocolError:
    _check("GET: 上限に達したら例外", True)
_check("GET: 試行は上限回数まで",
       calls["n"] == core._RETRY_MAX_ATTEMPTS, f"試行={calls['n']}")

print("\n[D] 転送以外の失敗は握り潰さない")
calls = _install(1, ValueError("列がありません"))
try:
    rb.send_with_retry(_Req("GET"))
    _check("転送以外の例外はそのまま上がる", False, "例外が出なかった")
except ValueError:
    _check("転送以外の例外はそのまま上がる", True)
_check("転送以外は再送しない", calls["n"] == 1, f"試行={calls['n']}")

print()
if failures:
    print(f"  {FAIL} {len(failures)}件 失敗")
    for f in failures:
        print(f"      {f}")
    sys.exit(1)
print(f"  {PASS} 全テスト PASS")
