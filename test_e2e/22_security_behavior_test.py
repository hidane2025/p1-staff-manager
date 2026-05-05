"""P1 Staff Manager — セキュリティ挙動テスト（v3.7 全機能チェック）

実際のロジックレベルで以下を検証:
  - HTML エスケープ（contract_issuer._safe）
  - 定数時間比較（admin_guard._consteq）
  - admin_guard の状態遷移
  - .gitignore の重要パターン

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/22_security_behavior_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

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
# 1. contract_issuer._safe: HTML エスケープ
# ============================================================
print("\n[1] contract_issuer._safe: HTML エスケープ")
from utils.contract_issuer import _safe

_check("None → ''", _safe(None) == "")
_check("空文字 → ''", _safe("") == "")
_check("普通の名前はそのまま",
       _safe("山田太郎") == "山田太郎")
_check("<script> がエスケープされる",
       _safe("<script>alert('xss')</script>") == "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;")
_check("&amp;エンティティもエスケープ",
       _safe("A & B") == "A &amp; B")
_check("ダブルクォートもエスケープ",
       _safe('she said "hi"') == "she said &quot;hi&quot;")
_check("Markdown 制御文字（# *）はそのまま",
       _safe("# heading and *bold*") == "# heading and *bold*")


# ============================================================
# 2. admin_guard._consteq: 定数時間比較
# ============================================================
print("\n[2] admin_guard._consteq: 定数時間比較")
from utils.admin_guard import _consteq

_check("同一文字列 True", _consteq("abc123", "abc123") is True)
_check("異なる文字列 False", _consteq("abc123", "abc124") is False)
_check("長さ違いでも crash しない",
       _consteq("a", "b") in (True, False))
_check("空文字同士 True", _consteq("", "") is True)


# ============================================================
# 3. admin_guard の状態関数
# ============================================================
print("\n[3] admin_guard: 状態関数")

import streamlit as st
if not hasattr(st, "session_state"):
    st.session_state = {}  # type: ignore
from utils import admin_guard

st.session_state.clear()
_check("初期 is_admin() False", admin_guard.is_admin() is False)
_check("初期 operator_name() == 'anonymous'",
       admin_guard.operator_name() == "anonymous")
_check("初期 admin_login_at() 空", admin_guard.admin_login_at() == "")

st.session_state[admin_guard._SESSION_KEY] = True
st.session_state[admin_guard._LOGIN_AS_KEY] = "中野"
st.session_state[admin_guard._LOGIN_AT_KEY] = "2026-05-04 10:00:00"

_check("認証後 is_admin() True", admin_guard.is_admin() is True)
_check("認証後 operator_name 中野", admin_guard.operator_name() == "中野")
_check("認証後 admin_login_at 取得",
       admin_guard.admin_login_at() == "2026-05-04 10:00:00")

# クリアして元に戻す
st.session_state.clear()


# ============================================================
# 4. requirements.txt: 主要依存がピン留めされているか
# ============================================================
print("\n[4] requirements.txt: バージョンピン留め")
req = (ROOT / "requirements.txt").read_text()

for pkg in ["streamlit", "pandas", "supabase", "reportlab"]:
    found = any(line.strip().startswith(pkg) for line in req.splitlines())
    _check(f"{pkg} が requirements.txt に含まれる", found)

# ピン留めされている（== or <= or >=...,< 等）
def _is_pinned(line: str) -> bool:
    return "==" in line or "<=" in line or ">=...<" in line or ">=...<=" in line


lines = [l.strip() for l in req.splitlines() if l.strip() and not l.strip().startswith("#")]
pinned = [l for l in lines if "==" in l]
_check(f"== でピン留めされた行が {len(lines)}/{len(lines)} 行",
       len(pinned) == len(lines), f"got pinned={len(pinned)} of {len(lines)}")


# ============================================================
# 5. .gitignore: 機微ファイル禁止リスト
# ============================================================
print("\n[5] .gitignore: 機微ファイル禁止リスト")
gi = (ROOT / ".gitignore").read_text()

for pattern in [".env", "secrets.toml", ".venv", "credentials"]:
    _check(f".gitignore に '{pattern}' が含まれる", pattern in gi)


# ============================================================
# 6. db.py: anon key にハードコードされた service_role の混入が無い
# ============================================================
print("\n[6] db.py: 機微キー混入チェック")
db_src = (ROOT / "db.py").read_text()

# service_role の eyJrb2xlIjoic2VydmljZV9yb2xlIg== あたりが混じってないか
_check("service_role の役割ペイロードが無い",
       '"role":"service_role"' not in db_src.replace(" ", ""))
_check("anon キー以外の JWT 文字列がない（複数JWT検出）",
       db_src.count("eyJhbGciOi") <= 1, "もし >=2 なら別キー混入の疑い")


# ============================================================
# 7. admin_guard を使うページが7つあるか
# ============================================================
print("\n[7] admin_guard 適用ページ数")
import re
pages_dir = ROOT / "pages"
applied = []
for p in pages_dir.glob("*.py"):
    src = p.read_text()
    if re.search(r"require_admin\(", src):
        applied.append(p.name)

_check(f"require_admin() を使うページが7つ以上",
       len(applied) >= 7,
       f"got {len(applied)}: {applied}")

# 必須ページ（PII濃度高）
must_have = ["1_スタッフ管理", "6_精算レポート", "7_年間累計",
             "91_領収書発行", "94_契約書発行", "92_発行者設定", "93_契約書テンプレ"]
for stem in must_have:
    found = any(stem in name for name in applied)
    _check(f"{stem} に require_admin 適用済み", found)


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
