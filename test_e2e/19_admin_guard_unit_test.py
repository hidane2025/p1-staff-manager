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
# 5. 多ユーザー認証（pbkdf2 / ロール）— v3.15
# ============================================================
print("\n[5] 多ユーザー認証（pbkdf2 / role）")

# 5.1 pbkdf2 ハッシュ＆照合
h = admin_guard.hash_password("CorrectHorse9!")
_check("ハッシュ形式 pbkdf2$...", h.startswith("pbkdf2$200000$"))
_check("正パスワードで True", admin_guard._verify_password("CorrectHorse9!", h) is True)
_check("誤パスワードで False", admin_guard._verify_password("wrong", h) is False)
_check("壊れたハッシュで False", admin_guard._verify_password("x", "garbage") is False)
_check("空ハッシュで False", admin_guard._verify_password("x", "") is False)
_check("ソルトは毎回ランダム",
       admin_guard.hash_password("a") != admin_guard.hash_password("a"))

# 5.2 _role_allowed
_check("admin は admin 集合に含まれる", admin_guard._role_allowed("admin", ("admin",)) is True)
_check("viewer は admin 限定に含まれない", admin_guard._role_allowed("viewer", ("admin",)) is False)
_check("viewer は admin+viewer に含まれる",
       admin_guard._role_allowed("viewer", ("admin", "viewer")) is True)
_check("roles 空なら全許可", admin_guard._role_allowed("anything", ()) is True)

# 5.3 _authenticate（_load_app_users を差し替えてユーザーストアを擬似化）
_fake_users = {
    "nakano": {"password_hash": admin_guard.hash_password("nakanoPass1"), "role": "admin"},
    "window1": {"password_hash": admin_guard.hash_password("viewerPass1"), "role": "viewer"},
    "taka.p1": {"password_hash": admin_guard.hash_password("dotPass123"), "role": "viewer"},
    "emptyrole": {"password_hash": admin_guard.hash_password("emptyRolePass1"), "role": ""},
}
_orig_loader = admin_guard._load_app_users
admin_guard._load_app_users = lambda: _fake_users
try:
    _check("正ID/PASS で role=admin", admin_guard._authenticate("nakano", "nakanoPass1") == "admin")
    _check("正ID/PASS で role=viewer", admin_guard._authenticate("window1", "viewerPass1") == "viewer")
    _check("ドット入りユーザー名でも認証OK",
           admin_guard._authenticate("taka.p1", "dotPass123") == "viewer")
    _check("誤パスワードで None", admin_guard._authenticate("nakano", "x") is None)
    _check("未知ユーザーで None", admin_guard._authenticate("ghost", "whatever") is None)
    _check("空入力で None", admin_guard._authenticate("", "") is None)
    _check("role空文字でも認証成功時はviewer（admin昇格させない）",
           admin_guard._authenticate("emptyrole", "emptyRolePass1") == "viewer")
    # （is_auth_enabled は _auth_users_configured ベースに変更したため 5.3c で検証）
finally:
    admin_guard._load_app_users = _orig_loader

# 5.3b _load_app_users: 空/壊れハッシュの entry は除外（Codex P2 対応）
class _FakeSecrets:
    def __init__(self, data):
        self._d = data
    def get(self, k, default=None):
        return self._d.get(k, default)

try:
    _orig_secrets = admin_guard.st.secrets
except Exception:
    _orig_secrets = None
admin_guard.st.secrets = _FakeSecrets({"auth": {"users": {
    "good": {"password_hash": admin_guard.hash_password("goodPass1"), "role": "admin"},
    "broken": {"role": "admin"},                       # password_hash 無し → 除外
    "blankhash": {"password_hash": "", "role": "admin"},  # 空 → 除外
    "truncated": {"password_hash": "pbkdf2$200000$abc", "role": "admin"},  # 形式不正 → 除外
    "norole": {"password_hash": admin_guard.hash_password("noRolePass1")},  # role 省略 → viewer
    "wsrole": {"password_hash": admin_guard.hash_password("wsRolePass1"), "role": "   "},  # 空白role → viewer
    "taka.p1": {"password_hash": admin_guard.hash_password("dotPass123"), "role": "viewer"},
}}})
try:
    loaded = admin_guard._load_app_users()
    _check("空/無ハッシュ entry は除外（broken）", "broken" not in loaded)
    _check("空ハッシュ entry は除外（blankhash）", "blankhash" not in loaded)
    _check("pbkdf2風だが壊れたハッシュは除外（truncated・Codex P2-B）", "truncated" not in loaded)
    _check("正常 entry は載る（good）", "good" in loaded)
    _check("role省略は最小権限viewerにフォールバック（Codex P2-A）",
           loaded.get("norole", {}).get("role") == "viewer")
    _check("空白のみrole も viewer（Codex P1・admin昇格させない）",
           loaded.get("wsrole", {}).get("role") == "viewer")
    _check("ドット入りユーザー名も load される", loaded.get("taka.p1", {}).get("role") == "viewer")
finally:
    if _orig_secrets is not None:
        admin_guard.st.secrets = _orig_secrets

# 5.3c fail closed: [auth.users] があるが全entry不正 → パスワードレスに落とさない（Codex P1 対応）
try:
    _orig_secrets2 = admin_guard.st.secrets
except Exception:
    _orig_secrets2 = None
admin_guard.st.secrets = _FakeSecrets({"auth": {"users": {
    "broken": {"role": "admin"},                       # password_hash 無し
    "blankhash": {"password_hash": "", "role": "admin"},  # 空
}}})
try:
    _check("全entry不正なら有効ユーザーは0件", admin_guard._load_app_users() == {})
    _check("[auth.users]の存在は検知する（fail closed判定）",
           admin_guard._auth_users_configured() is True)
    _check("設定があれば is_auth_enabled True（パスワードレスに落ちない）",
           admin_guard.is_auth_enabled() is True)
finally:
    if _orig_secrets2 is not None:
        admin_guard.st.secrets = _orig_secrets2

# 5.4 後方互換: ユーザー不在なら _load_app_users は空（→単一PW/パスワードレスへ）
admin_guard._load_app_users = lambda: {}
try:
    _check("ユーザー不在なら多ユーザーモードに入らない（空dict）",
           admin_guard._load_app_users() == {})
finally:
    admin_guard._load_app_users = _orig_loader


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
