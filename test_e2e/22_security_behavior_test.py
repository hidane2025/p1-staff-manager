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
# 9. ダウンロードされるファイル名に2バイト文字を使っていないか
#    （木村さん指摘 2026-07-29: 日本語ファイル名は環境によって
#     文字化け・保存失敗を起こす。特にスタッフ125名のスマホが対象）
# ============================================================
print("\n[9] ダウンロード名の2バイト文字チェック")
import re as _re2
_bad = []
for _py in list(ROOT.glob("pages/*.py")) + list(ROOT.glob("staff_site/pages/*.py")):
    for _m in _re2.finditer(r'file_name=([^,\n]+)', _py.read_text()):
        _lit = _m.group(1)
        if any(ord(_c) > 127 for _c in _lit):
            _bad.append(f"{_py.name}: {_lit.strip()}")
_check("file_name に非ASCII文字が含まれていない", not _bad, f"該当: {_bad}")


# ============================================================
# 10. 2026-07-29 の是正が巻き戻っていないか（Codex独立レビュー対応）
# ============================================================
print("\n[10] データ消失・fail-open の再発防止")
_db_src = (ROOT / "db.py").read_text()
_guard_src = (ROOT / "utils/admin_guard.py").read_text()
_mon_src = (ROOT / "utils/monitoring.py").read_text()
_url_src = (ROOT / "utils/url_helper.py").read_text()

# 支払い保存が「削除→挿入」に戻っていないか（削除に成功して挿入で失敗するとデータが消える）
_save_block = _db_src[_db_src.index("def save_payment("):_db_src.index("def set_payment_adjustment(")]
_check("save_payment が支払いレコードを delete しない",
       'p1_payments").delete()' not in _save_block,
       "delete→insert はデータ消失経路")
_check("save_payment の更新に支払済みガードがある",
       'neq("status", "paid")' in _save_block)

# 未承認へ戻す処理の競合ガード
_reset_block = _db_src[_db_src.index("def reset_payment_to_pending("):_db_src.index("def mark_absent(")]
_check("reset_payment_to_pending の更新に支払済みガードがある",
       'neq("status", "paid")' in _reset_block)

# 日別単価が消える経路
_rate_block = _db_src[_db_src.index("def set_event_rate("):]
_rate_block = _rate_block[:_rate_block.index("def ", 10)]
_check("set_event_rate が delete を使わない", '.delete()' not in _rate_block)

# TOTPのfail-open
_check("TOTP照会失敗を未設定と区別する例外がある", "class TotpLookupError" in _db_src)
_check("照会失敗時にログインを止める", "TotpLookupError" in _guard_src and "st.stop()" in _guard_src)

# 監視: 送信成功後に抑制記録する（失敗しても再送できる）
_check("監視は送信成功後に重複記録する", "_record_sent(key)" in _mon_src)
_check("通知本文に例外メッセージを載せない", "_exc_type" in _mon_src)

# URL生成: 旧環境へのフォールバックを持たない
_check("旧Streamlit URLへのフォールバックが無い",
       "streamlit.app" not in _url_src)
_check("トークンをURLエンコードしている", "_quote(" in _url_src)

# セッション期限
_check("管理セッションに有効期限がある",
       "_SESSION_ABSOLUTE_HOURS" in _guard_src and "_SESSION_IDLE_MINUTES" in _guard_src)

# コンテナ権限・レート制限
_dockerfile = (ROOT / "Dockerfile").read_text()
_nginx = (ROOT / "deploy/nginx.conf.template").read_text()
_entry = (ROOT / "deploy/entrypoint.sh").read_text()
_check("非特権ユーザーを作成している", "useradd" in _dockerfile)
_check("Streamlitを非特権で起動している", "setpriv" in _entry)
_check("Basic認証情報をアプリに渡していない", "-u BASIC_AUTH_PASSWORD" in _entry)
_check("IP単位のレート制限がある", "limit_req_zone" in _nginx and "limit_req zone=" in _nginx)
_check("同時接続数の制限がある", "limit_conn" in _nginx)
_check("起動時にDB到達性を検査する", "connection_health" in _entry)
_check("障害対応手順書が存在する", (ROOT / "deploy/RUNBOOK.md").exists())


# ============================================================
# 11. DB整合性ガード（2026-08-02 外部エンジニア点検の指摘3件）
#     マイグレーションSQLが存在し、必要な制約を定義しているかを検査する。
#     （実DBへの適用状況は別途 docs/schema.sql の再生成で確認する）
# ============================================================
print("\n[11] DB整合性ガードの定義")
_guard_sql_path = ROOT / "docs/db_migrations/20260802_add_integrity_guards.sql"
_check("整合性ガードのマイグレーションが存在する", _guard_sql_path.exists())
if _guard_sql_path.exists():
    _g = _guard_sql_path.read_text()
    _check("契約書がスタッフ削除で消えない（RESTRICT化）",
           "p1_contracts" in _g and "ON DELETE RESTRICT" in _g)
    _check("給与の二重払いを禁止（event_id, staff_id の一意制約）",
           "p1_payments" in _g and "UNIQUE (event_id, staff_id)" in _g)
    _check("同日レートの重複を禁止（event_id, date の一意制約）",
           "p1_event_rates" in _g and "UNIQUE (event_id, date)" in _g)
    _check("個別手当・交通費もスタッフ削除で消えない",
           "p1_staff_event_allowances" in _g and "p1_transport_claims" in _g)


# ============================================================
# 12. 全Pythonファイルの構文健全性（2026-08-02）
#     lint が staff_site/ を対象外にしており、構文エラーのページを
#     本番へ出しかけた（UIテストが拾って発覚）。母集団をgit管理下に固定する。
# ============================================================
print("\n[12] 全Pythonファイルの構文健全性")
import ast as _ast, subprocess as _sp
_files = _sp.run(["git", "ls-files", "*.py"], cwd=str(ROOT),
                 capture_output=True, text=True).stdout.split()
_bad_syntax, _bad_future = [], []
for _f in _files:
    _src = (ROOT / _f).read_text()
    try:
        _t = _ast.parse(_src)
    except SyntaxError as _e:
        _bad_syntax.append(f"{_f}: {_e.msg}")
        continue
    # from __future__ は docstring の直後でなければ SyntaxError になる
    _body = [n for n in _t.body
             if not (isinstance(n, _ast.Expr) and isinstance(getattr(n, "value", None), _ast.Constant)
                     and isinstance(n.value.value, str))]
    for _i, _n in enumerate(_body):
        if isinstance(_n, _ast.ImportFrom) and _n.module == "__future__" and _i > 0:
            _bad_future.append(f"{_f}（{_i+1}番目）")

_check(f"git管理下の全{len(_files)}ファイルが構文エラー無し", not _bad_syntax, f"{_bad_syntax}")
_check("from __future__ が先頭に置かれている", not _bad_future, f"{_bad_future}")


# ============================================================
# 13. 交通費の上限解釈が3画面で一致しているか（2026-08-02 → 2026-08-04改）
#     2026-08-02: 「総額」と「日額×勤務日数」の分裂を発見し、いったん総額へ統一。
#     2026-08-04: 承認済みの業務ルール（交通費統一ルール 2026-07-22 TAKA起草・
#     木村さん基本承認）が「開催地=出勤1日あたり一律／遠方=往復総額の上限」
#     だったため、開催地のみ日額×日数へ再統一。3画面が同じ式であることを固定する。
# ============================================================
print("\n[13] 交通費の上限解釈の一致")
_pit = (ROOT / "pages/10_pit_terminal.py").read_text()
_pay = (ROOT / "pages/3_payment.py").read_text()
_tra = (ROOT / "pages/8_transport.py").read_text()

_check("ピット端末: 開催地は日額×勤務日数",
       "approved = max_amt * days_worked" in _pit,
       "開催地の総額支給は承認ルール（出勤1日あたり一律）と食い違う")
_check("ピット端末: 遠方は領収書と往復総額上限の低い方",
       "approved = min(receipt_amt, max_amt)" in _pit,
       "遠方上限の日数倍は同じ人の精算額が画面で変わる事故に戻る")
_check("支払い計算: 開催地は日額×勤務日数",
       'per_day * days, f"開催地一律' in _pay,
       "支払い計算だけ総額だとピット端末・見積と金額が食い違う")
_check("交通費ページ: 遠方は総額として上限を適用",
       "if receipt > limit and limit > 0" in _tra)
_check("交通費ページ: 開催地見積はスタッフ別シフト日数を使う",
       "_days_by_staff" in _tra,
       "見積が日額のままだと銀行の現金準備が日数分不足する")

# 0円確定を黙って通さないこと（未払いに気づける導線）
_check("交通費0円の理由が画面に出る", "transport_zero" in _pay)
_check("打刻ミスで除外した日が画面に出る", "invalid_shift_notes" in _pay)


# ============================================================
# 14. 実行環境の一致（2026-08-04 UI運用テストで発覚）
#     本番は python:3.12-slim、CI/ローカルは 3.9 だった。
#     pages/3_payment.py が 3.10+ 構文（int | None）を使っており、
#     「支払い額を計算」ボタンが 3.9 では TypeError で動かなかった。
#     最も金額に効く機能が、CIでもローカルでも一度も実行されていなかった。
# ============================================================
print("\n[14] 実行環境の一致と構文の互換性")
import re as _re3, subprocess as _sp3
_dockerfile = (ROOT / "Dockerfile").read_text()
_m = _re3.search(r"FROM python:(\d+)\.(\d+)", _dockerfile)
_check("Dockerfile が Python バージョンを固定している", bool(_m), _dockerfile[:60])

_ci_path = ROOT / ".github/workflows/test.yml"
if _ci_path.exists() and _m:
    _ci = _ci_path.read_text()
    _prod_ver = f"{_m.group(1)}.{_m.group(2)}"
    _check(f"CIのPythonが本番と一致（{_prod_ver}）",
           f"'{_prod_ver}'" in _ci or f'"{_prod_ver}"' in _ci,
           "CIと本番でバージョンが違うと、本番でしか動かない/落ちるコードを検出できない")

# 3.10+ 構文を使うなら from __future__ import annotations が必要（3.9互換のため）
_pep604 = []
for _f in _sp3.run(["git","ls-files","*.py"], cwd=str(ROOT),
                   capture_output=True, text=True).stdout.split():
    _src = (ROOT / _f).read_text()
    if "from __future__ import annotations" in _src:
        continue
    if _re3.search(r"->\s*[\w\[\], ]*\|\s*None|:\s*\w+\s*\|\s*None\s*[,)=]", _src):
        _pep604.append(_f)
_check("3.10+の型構文を使うファイルは __future__ を宣言している",
       not _pep604, f"未宣言: {_pep604}")


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
