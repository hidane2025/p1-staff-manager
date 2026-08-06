"""db.py(1,822行)を dbx/ パッケージへ機械分割する（挙動不変・順序保存）

- 全トップレベル定義を名前→モジュール表で振り分け（未登録名があれば即エラー）
- 各モジュールは元の import 群を共通ヘッダとして持つ
- get_client/log_action/_now は core 経由の呼び出しに書き換え
  （テストの get_client 差し替え(_fake_db)が全モジュールに効くようにするため）
- その他のモジュール跨ぎ参照は自動検出して from-import を生成
- db.py は互換窓口（re-export）になる
"""
from __future__ import annotations

import ast
import pathlib
import re
from collections import defaultdict

ROOT = pathlib.Path.home() / "Documents/GitHub/p1-staff-manager"
SRC = (ROOT / "db.py").read_text()
LINES = SRC.splitlines(keepends=True)
TREE = ast.parse(SRC)

ROUTE = {}
def route(mod, names):
    for n in names.split():
        ROUTE[n] = mod

route("core", "_JST _DEFAULT_SUPABASE_URL _DEFAULT_SUPABASE_KEY _sanitize_key "
      "supabase_key_role _get_supabase_config connection_health get_client _now "
      "log_action get_audit_log init_db _flatten_staff_join")
route("staff", "create_staff get_all_staff get_staff_by_id update_staff _norm_key "
      "_build_staff_index _match_staff _index_add bulk_import_staff find_or_create_staff")
route("transport", "get_transport_rules save_transport_rules get_transport_claims "
      "upsert_transport_claim get_staff_region")
route("events", "create_event update_event_meta get_all_events get_event_by_id "
      "set_event_rate get_event_rates bulk_set_event_rates")
route("shifts", "upsert_shift get_shifts_for_event "
      "_revert_payment_if_amount_affected checkin_staff checkout_staff bulk_checkout "
      "LUNCH_STATUSES LUNCH2_THRESHOLD_MINUTES _validate_lunch_status "
      "update_lunch_status bulk_set_lunch_status get_lunch_summary DISTRIBUTION_KINDS "
      "planned_shift_minutes _distribution_column update_distribution_status "
      "bulk_set_distribution_status get_handout_summary mark_absent set_shift_mix")
route("auth", "_PBKDF2_ITERATIONS _hash_day_code issue_day_code verify_day_code is_day_code_active "
      "list_day_codes revoke_day_code TotpLookupError get_totp set_totp hash_password "
      "list_app_users get_app_users_for_auth AppUserLookupError create_app_user "
      "set_app_user_password update_app_user touch_app_user_login")
route("payments", "reset_payment_to_pending rounding_supported get_event_rounding_unit "
      "compute_payable_amount get_payable save_payment set_payment_adjustment "
      "recompute_payable_for_event get_payments_for_event get_yearly_totals "
      "approve_payment mark_paid mark_receipt_received get_individual_allowances "
      "add_individual_allowance remove_individual_allowance _allowance_default_label "
      "add_petty_cash get_petty_cash_for_event")

CORE_CALLS = {"get_client", "log_action", "_now"}  # core.xxx() 経由に書き換える

def node_name(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None

# ヘッダ = docstring + import 群
header_parts = []
body_nodes = []
def _is_import_try(node):
    return (isinstance(node, ast.Try)
            and all(isinstance(s, (ast.Import, ast.ImportFrom, ast.Assign))
                    for s in node.body + sum([h.body for h in node.handlers], [])))

for node in TREE.body:
    if isinstance(node, (ast.Import, ast.ImportFrom)) or _is_import_try(node):
        header_parts.append(ast.get_source_segment(SRC, node))
    elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
          and isinstance(node.value.value, str) and not body_nodes):
        pass  # 元docstringは各モジュールで独自に書く
    else:
        body_nodes.append(node)
HEADER = "\n".join(header_parts) + "\n"

# チャンク切り出し: 全トップレベルノードを元の順で歩き、import類は読み飛ばして
# prev_end だけ進める（間のコメントは次の定義チャンクに付く）
chunks = []  # (name, module, text, node)
prev_end = 0
if TREE.body and isinstance(TREE.body[0], ast.Expr):
    prev_end = TREE.body[0].end_lineno  # 元docstring
for node in TREE.body:
    if node.end_lineno <= prev_end:
        continue
    if isinstance(node, (ast.Import, ast.ImportFrom)) or _is_import_try(node):
        prev_end = node.end_lineno
        continue
    name = node_name(node)
    if name is None:
        raise SystemExit(f"想定外のトップレベル文 at line {node.lineno}")
    if name not in ROUTE:
        raise SystemExit(f"振り分け未登録: {name} (line {node.lineno})")
    text = "".join(LINES[prev_end:node.end_lineno])
    chunks.append((name, ROUTE[name], text, node))
    prev_end = node.end_lineno

body_nodes = [n for _, _, _, n in chunks]
tail = "".join(LINES[prev_end:])
if tail.strip():
    raise SystemExit(f"末尾に未処理テキスト: {tail[:100]!r}")

# モジュール別に集約
mods = defaultdict(list)
defined_in = {}
for name, mod, text, node in chunks:
    mods[mod].append((name, text, node))
    defined_in[name] = mod

MOD_DOC = {
    "core": "接続・監査ログなどの基盤（get_client の差し替え点はここ）",
    "staff": "スタッフ台帳と名寄せ",
    "transport": "交通費ルール・領収書請求",
    "events": "イベントと日別単価",
    "shifts": "シフト・出退勤・配布チェック",
    "auth": "当日運用コード・TOTP・個人アカウント",
    "payments": "支払い・承認・個別手当・小口",
}

(ROOT / "dbx").mkdir(exist_ok=True)
(ROOT / "dbx/__init__.py").write_text(
    '"""P1 Staff Manager DBアクセス層（2026-08-06 に db.py から機械分割）\n\n'
    '呼び出し側は従来どおり `import db` の互換窓口を使う。\n"""\n')

for mod, items in mods.items():
    used = set()
    for _, _, node in items:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                used.add(sub.id)
    cross = defaultdict(set)
    needs_core = False
    for u in sorted(used):
        owner = defined_in.get(u)
        if owner and owner != mod:
            if u in CORE_CALLS:
                needs_core = True
            else:
                cross[owner].add(u)
    body = "".join(t for _, t, _ in items)
    if needs_core and mod != "core":
        for fn in CORE_CALLS:
            body = re.sub(rf"(?<![\w.]){fn}\(", f"core.{fn}(", body)
    imports = []
    if needs_core and mod != "core":
        imports.append("from dbx import core")
    for owner, names in sorted(cross.items()):
        # core関数の直接importはしない（差し替えが効かなくなる）
        names = sorted(n for n in names if not (owner == "core" and n in CORE_CALLS))
        if names:
            imports.append(f"from dbx.{owner} import {', '.join(names)}")
    text = (f'"""{MOD_DOC[mod]}（db.py から2026-08-06に機械分割・挙動不変）"""\n'
            + HEADER + "\n" + "\n".join(imports) + ("\n" if imports else "") + body)
    (ROOT / f"dbx/{mod}.py").write_text(text)
    print(f"dbx/{mod}.py: {len(items)}定義 / cross={dict((k, len(v)) for k, v in cross.items())} core経由={needs_core}")

# 互換窓口 db.py
facade = '''"""P1 Staff Manager — DBアクセス層（互換窓口）

2026-08-06 リファクタリング: 実体は dbx/ パッケージへ分割した（挙動不変）。
呼び出し側は従来どおり `import db` → `db.関数()` を使えばよい。
分割の狙い: 1,822行の単一ファイルで衝突・見通し悪化が起きていたため、
ドメイン別（core/staff/events/shifts/transport/payments/auth）に整理した。

テストで接続先を差し替える場合は dbx.core.get_client を差し替えること
（test_e2e/_fake_db.py が対応済み）。
"""

from dbx.core import *  # noqa: F401,F403
from dbx.staff import *  # noqa: F401,F403
from dbx.transport import *  # noqa: F401,F403
from dbx.events import *  # noqa: F401,F403
from dbx.shifts import *  # noqa: F401,F403
from dbx.auth import *  # noqa: F401,F403
from dbx.payments import *  # noqa: F401,F403

# 外部から参照されている内部ヘルパーの互換維持
from dbx.staff import _norm_key  # noqa: F401  (test_e2e/23 名寄せテスト)
from dbx.payments import _allowance_default_label  # noqa: F401  (pages/11)
from dbx.core import _now  # noqa: F401
'''
(ROOT / "db.py").write_text(facade)
print("db.py 互換窓口を生成")

# 公開名の完全一致検証
old_names = {node_name(n) for n in body_nodes}
import subprocess, sys as _s
r = subprocess.run([str(ROOT / ".venv/bin/python"), "-c",
    "import sys; sys.path.insert(0, %r); import db; print('\\n'.join(dir(db)))" % str(ROOT)],
    capture_output=True, text=True)
if r.returncode:
    print("importエラー:\n", r.stderr[-1500:]); raise SystemExit(1)
new_names = set(r.stdout.split())
missing = {n for n in old_names if n not in new_names}
print("旧db.pyの定義数:", len(old_names), "/ 新窓口に無い名前:", missing or "なし ✅")
