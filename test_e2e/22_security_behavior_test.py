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
# 5.5 Codex 4回目 P1 #7 (2026-05-09): 個別手当テーブルのRLS設定
# ============================================================
print("\n[5.5] 個別手当テーブルのRLS+ポリシー定義（マイグレSQL検証）")
allowance_sql = (ROOT / "docs/db_migrations/20260508_add_individual_allowances.sql").read_text()

_check("ENABLE ROW LEVEL SECURITY が含まれる",
       "ENABLE ROW LEVEL SECURITY" in allowance_sql)
_check("anon 拒否ポリシー（USING (false)）が含まれる",
       "USING (false)" in allowance_sql)
_check("anon ロールへの ALL FOR 制限が含まれる",
       "TO anon" in allowance_sql)
_check("service_role 許可ポリシーが含まれる",
       "service_role" in allowance_sql)
# Codex 5回目 P1 #11 (2026-05-09): authenticated は許可しない
import re
_active_policy_block = re.search(
    r'CREATE POLICY "p1_allowances_service_role_all"[^;]*;',
    allowance_sql, re.DOTALL,
)
_check("有効ポリシーに authenticated は含まれない（コメント例除く）",
       _active_policy_block is not None
       and "authenticated" not in _active_policy_block.group(0))


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

# 2026-07-28: ページ名の英字化に伴い「特定ファイル名の列挙」をやめ、
# 「トークンURL型の2ページ以外は全部ゲート必須」という不変条件で検査する。
# 列挙方式はページ追加・改名のたびに検査漏れを生む（実際に改名で空振りした）。
# 2026-07-29: スタッフ用2ページは staff_site/ へ物理分離したため、
# pages/ 配下は「全てゲート必須」が正しい不変条件になった。
TOKEN_PAGES: set[str] = set()
ungated = sorted(
    p.name for p in pages_dir.glob("*.py")
    if p.name not in TOKEN_PAGES and p.name not in applied
)
_check("トークンURL型の2ページ以外は全て require_admin 適用済み",
       not ungated,
       f"未ゲート: {ungated}")

# 逆方向: スタッフ本人が開く2ページに管理者ゲートを付けてしまっていないか
for name in sorted(TOKEN_PAGES):
    _check(f"{name} は管理者ゲート無し（スタッフ本人が開くため）",
           name not in applied)


# ============================================================
# 8. Railwayヘルスチェックが Basic認証の外側を指しているか
#    （2026-07-29 事故: /_stcore/health を指定していたが、この経路は
#     Basic認証の内側で401になり、デプロイが3回失敗した）
# ============================================================
print("\n[8] ヘルスチェックのパスと認証範囲の整合")
import json as _json
_railway = _json.loads((ROOT / "railway.json").read_text())
_hc = _railway.get("deploy", {}).get("healthcheckPath", "")
_check("healthcheckPath が設定されている", bool(_hc), _hc)
_check("healthcheckPath は認証免除の /staff/ 配下を指している",
       _hc.startswith("/staff/"),
       f"{_hc} は Basic認証の内側のため 401 になりデプロイが失敗する")

_nginx = (ROOT / "deploy/nginx.conf.template").read_text()
_check("nginxに /staff/ の認証免除ブロックがある",
       "location ^~ /staff/" in _nginx and "auth_basic off" in _nginx)
_check("管理側 location / は認証必須のまま",
       "auth_basic \"P1 Staff Manager\"" in _nginx)
_check("/_stcore/ を丸ごと認証免除にしていない（2026-07-28の設計欠陥の再発防止）",
       "location /_stcore/" not in _nginx)


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
