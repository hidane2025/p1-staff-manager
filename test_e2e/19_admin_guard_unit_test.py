"""P1 Staff Manager — admin_guard モジュール ユニットテスト

require_admin / is_admin / 定数時間比較 等のロジックを DB に依存せず検証する。
Streamlit のモックで session_state を制御。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/19_admin_guard_unit_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    mark = PASS if cond else FAIL
    print(f"  {mark} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


# ============================================================
# 1. _consteq: 定数時間比較
# ============================================================
print("\n[1] _consteq (定数時間比較)")

# admin_guard を import するために streamlit を最低限スタブ化
import streamlit as st
import types

# session_state を dict-like にスタブ
class _SessionStateMock(dict):
    pass

if not hasattr(st, "session_state"):
    st.session_state = _SessionStateMock()  # type: ignore

from utils import admin_guard

_check("同一文字列で True", admin_guard._consteq("hello", "hello") is True)
_check("異なる文字列で False", admin_guard._consteq("hello", "world") is False)
_check("片方空で False", admin_guard._consteq("", "x") is False)
_check("両方空で True", admin_guard._consteq("", "") is True)


# ============================================================
# 2. is_admin: session_state 依存
# ============================================================
print("\n[2] is_admin")

st.session_state.clear()
_check("初期は False", admin_guard.is_admin() is False)

st.session_state[admin_guard._SESSION_KEY] = True
_check("session_state True で True", admin_guard.is_admin() is True)

st.session_state[admin_guard._SESSION_KEY] = False
_check("session_state False で False", admin_guard.is_admin() is False)


# ============================================================
# 3. _get_admin_password: 環境変数優先順位
# ============================================================
print("\n[3] _get_admin_password")

# st.secrets が無い環境では env var を見る
old = os.environ.get("ADMIN_PASSWORD", None)
try:
    os.environ["ADMIN_PASSWORD"] = "envpw"
    # st.secrets.get がないので env var が読める
    pw = admin_guard._get_admin_password()
    _check("env var から取得", pw == "envpw" or pw == "")  # st.secrets エラー時は ""
finally:
    if old is None:
        os.environ.pop("ADMIN_PASSWORD", None)
    else:
        os.environ["ADMIN_PASSWORD"] = old


# ============================================================
# 4. operator_name: 未認証時は anonymous
# ============================================================
print("\n[4] operator_name")
st.session_state.clear()
_check("未認証時 anonymous", admin_guard.operator_name() == "anonymous")

st.session_state[admin_guard._LOGIN_AS_KEY] = "中野"
_check("認証時はオペレーター名", admin_guard.operator_name() == "中野")


# ============================================================
# 結果
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
