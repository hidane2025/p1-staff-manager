"""P1 Staff Manager — タイムゾーン回帰テスト（2026-08-02 QA検出欠陥）

■ 何の欠陥を再現するか
    本番コンテナは python:3.12-slim で、TZ を設定しなければ **UTC** で動く。
    このとき引数なしの `datetime.now()`（naive＝タイムゾーン情報なし）は
    「OSのローカル時刻」＝UTCの壁時計を返す。日本時間より **9時間前** である。

    実害（QAで確定した3点）:
      ① pages/5_attendance.py の today_str
         JST 8/3 00:30 に開くと UTC は 8/2 15:30。「今日」が前日になり、
         is_today 判定が外れて「現在時刻までの予定者を出勤」ボタンが
         当日のシフトに効かなくなる。
      ② 同 now_str
         現在時刻フィルタ（planned_start <= now_str）が9時間前の時刻で効くため、
         すでに出勤している人が一括出勤の対象から漏れる。
      ③ 同「凍結退勤 → 退勤時刻（時）」の既定値
         JST 01:00（イベント運用上の25:00）に凍結すると既定が **UTC の 16** になる。
         18:00 出勤より前の退勤時刻として保存されると
         calculate_shift_hours() が total <= 0 で全項目 0 を返し（utils/calculator.py:112）、
         基本給が ¥0 になる。金額事故に直結する。

■ 正しく実装されている側（回帰させないための比較対象）
    pages/10_pit_terminal.py:54 と utils/admin_guard.py:44 は
    `_JST = timezone(timedelta(hours=9))` を定義し、`datetime.now(_JST)` を使っている。
    db.py:11 も同じ。この作法を全ページの基準とする。

■ テスト方針
    ・DBに接続しない（rule: 本番DB禁止）。DBを触る箇所は test_e2e/_fake_db.py で差し替える。
    ・時刻は「凍結」する。実行時刻に依存すると、たまたま通る/落ちるテストになるため、
      datetime を差し替えて UTC コンテナ上の特定の瞬間を再現する。
    ・ページ本体は Streamlit スクリプトで import できないので、
      AST でソースから該当式だけを取り出して評価する。
      文字列マッチではなく式を実際に走らせるので、
      「_JST を書いたが使っていない」といった見せかけの修正では通らない。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/33_timezone_regression_test.py
"""

from __future__ import annotations

import ast
import datetime as _dtmod
import glob
import os
import re
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    mark = PASS if cond else FAIL
    print(f"  {mark} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


# ============================================================
# 共通ヘルパー
# ============================================================

# JST は固定オフセット UTC+9（日本には夏時間が無いので固定で正しい）
JST = timezone(timedelta(hours=9))

# 現在時刻を取りうる呼び出し名。エイリアス（_dtn 等）も拾えるよう末尾の名前だけ見る。
_DT_ALIASES = {"datetime", "date", "_dtn", "_dt", "dt", "_datetime"}
_NOW_ATTRS = {"now", "today", "utcnow"}

# tz を渡す方法は now(tz) と now(tz=...) の2通りある。両方を「tz付き」と認める。
_TZ_KWARGS = {"tz", "tzinfo"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _dt_aliases(tree: ast.Module) -> set:
    """そのファイルが datetime / date をどんな名前で束縛しているか集める。

    `from datetime import datetime as _dtn` のような別名を付けられても検出漏れしないよう、
    固定リストではなく import 文から実際に読み取る。
    """
    aliases = set(_DT_ALIASES)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] == "datetime":
                    aliases.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
            for a in node.names:
                if a.name in ("datetime", "date"):
                    aliases.add(a.asname or a.name)
    return aliases


def _naive_now_calls(path: Path) -> list:
    """ソース中の naive（tz無し）な現在時刻取得を列挙して [(行番号, 式), ...] を返す。

    naive と判定するもの:
      - datetime.now()          … 引数なし。OSのローカル時刻＝コンテナでは UTC
      - datetime.today()        … 常に naive（tz を渡す口が無い）
      - datetime.utcnow()       … 常に naive。しかも中身は UTC で二重に紛らわしい
      - date.today()            … 日付が9時間ずれる本命
    tz付き（datetime.now(_JST) / datetime.now(tz=JST)）は正常として除外する。
    """
    found = []
    tree = ast.parse(_read(path))
    aliases = _dt_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_src = ast.unparse(node.func)
        head, _, attr = func_src.rpartition(".")
        if attr not in _NOW_ATTRS:
            continue
        if head.split(".")[-1] not in aliases:
            continue  # st.now() のような無関係な呼び出しを巻き込まない
        if attr in ("today", "utcnow"):
            found.append((node.lineno, ast.unparse(node)))
            continue
        # tz を渡していても中身が None なら naive と同じ（now(None) / now(tz=None)）
        tz_args = list(node.args) + [k.value for k in node.keywords if k.arg in _TZ_KWARGS]
        has_tz = bool(tz_args) and not all(
            isinstance(a, ast.Constant) and a.value is None for a in tz_args
        )
        if not has_tz:
            found.append((node.lineno, ast.unparse(node)))
    return found


# 名前空間を組むときに実行してよいモジュール。
# ここを datetime 系に絞ることで、streamlit / db を import せずに済ませる
# （＝ページの副作用も本番DB接続も起こさない）。
_SAFE_IMPORT_MODULES = {
    "datetime", "zoneinfo", "backports.zoneinfo", "pytz", "dateutil", "dateutil.tz", "time",
}


def _module_namespace(path: Path) -> dict:
    """ページのモジュールレベルから「時刻計算に必要な名前だけ」を再現した名前空間を作る。

    やること:
      1. datetime系の import 文だけを実行する（streamlit / db は入れない）
      2. モジュールレベルの単純代入を上から順に eval してみて、成功したものだけ束縛する
         → `_JST = timezone(timedelta(hours=9))` は成功して入る
         → `event_id = select_event(...)` は NameError で落ちるので入らない（＝副作用ゼロ）
    """
    ns: dict = {}
    tree = ast.parse(_read(path))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = node.module if isinstance(node, ast.ImportFrom) else None
            names = [mod] if mod else [a.name for a in node.names]
            if all((n or "").split(".")[0] in {m.split(".")[0] for m in _SAFE_IMPORT_MODULES}
                   for n in names):
                try:
                    exec(compile(ast.Module(body=[node], type_ignores=[]), "<ns>", "exec"), ns)
                except Exception:
                    pass
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            try:
                ns[node.targets[0].id] = eval(ast.unparse(node.value), ns)
            except Exception:
                pass  # ページ固有の関数呼び出し等。時刻計算には不要なので無視
    return ns


def _freeze(ns: dict, instant_jst: datetime) -> dict:
    """名前空間の datetime を「UTCコンテナ上のある瞬間」に固定した版へ差し替える。

    naive な now() は UTC の壁時計を返す ＝ 本番コンテナ（TZ未設定）の再現。
    tz を渡した now(tz) は正しく変換される ＝ 修正後の期待挙動。
    """
    utc_wall = instant_jst.astimezone(timezone.utc).replace(tzinfo=None)

    class _FrozenDateTime(_dtmod.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return utc_wall            # TZ未設定コンテナのローカル時刻＝UTC
            return instant_jst.astimezone(tz)

        @classmethod
        def today(cls):
            return utc_wall

        @classmethod
        def utcnow(cls):
            return utc_wall

    frozen_ns = dict(ns)
    for key, val in list(frozen_ns.items()):
        if val is _dtmod.datetime:
            frozen_ns[key] = _FrozenDateTime
        elif val is _dtmod:
            shim = types.ModuleType("datetime")
            for attr in dir(_dtmod):
                setattr(shim, attr, getattr(_dtmod, attr))
            shim.datetime = _FrozenDateTime
            frozen_ns[key] = shim
    return frozen_ns


def _find_assign_expr(path: Path, var: str):
    """モジュールレベル代入 `var = <式>` の右辺ソースを返す（無ければ None）。"""
    tree = ast.parse(_read(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == var:
            return ast.unparse(node.value)
    return None


def _find_widget_kwarg(path: Path, label: str, kwarg: str):
    """`st.number_input("<label>", ..., <kwarg>=<式>)` の式ソースを返す（無ければ None）。"""
    tree = ast.parse(_read(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not ast.unparse(node.func).endswith("number_input"):
            continue
        if not (node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == label):
            continue
        for k in node.keywords:
            if k.arg == kwarg:
                return ast.unparse(k.value)
    return None


def _eval_frozen(path: Path, expr: str, instant_jst: datetime):
    """ページの名前空間＋凍結時刻で式を評価する。"""
    return eval(expr, _freeze(_module_namespace(path), instant_jst))


# ============================================================
# 0. 事前準備：DBスタブ（本番DBに触らない）
# ============================================================
print("\n[0] 準備: DBスタブ導入（本番DBには接続しない）")
from _fake_db import install_fake_db

install_fake_db()
import db  # noqa: E402  install_fake_db 後に import する

_check("db.get_client がスタブに差し替わっている",
       type(db.get_client()).__name__ == "FakeClient",
       f"got {type(db.get_client()).__name__}")


# ============================================================
# 1. [A] pages/*.py が naive な datetime.now() を使っていないこと
#
#    なぜ pages だけか:
#      pages 配下は画面に出る日付・時刻と、DBへ書く実績時刻を作る層。
#      ここが naive だと「表示が前日」「勤務時間が負」といった業務事故になる。
#      utils/ 配下のログ用タイムスタンプ（監査ログの記録時刻など）は
#      ①既に全て JST 実装済み（utils/contract_db.py, receipt_db.py 等）
#      ②仮にずれても金額・日付判定を壊さない
#      ので本テストの対象外にしている。回帰の主戦場は pages である。
# ============================================================
print("\n[1] [A] pages/*.py に naive な datetime.now() が無いこと")

page_files = sorted(Path(ROOT, "pages").glob("*.py"))
_check("pages/*.py を検出できた", len(page_files) > 0, f"got {len(page_files)}")

all_offenders = []
for page in page_files:
    offenders = _naive_now_calls(page)
    all_offenders += [(page.name, ln, src) for ln, src in offenders]
    _check(
        f"pages/{page.name}: 現在時刻はすべて tz 付き",
        not offenders,
        "naive: " + ", ".join(f"L{ln} {src}" for ln, src in offenders),
    )

_check(
    "naive な現在時刻取得の総数が 0",
    not all_offenders,
    "コンテナは TZ=UTC。tz無しの now() は JST より9時間前を返す → "
    + "; ".join(f"pages/{f}:{ln} {s}" for f, ln, s in all_offenders),
)


# ============================================================
# 2. [A-2] 出退勤ページ: today_str / now_str が JST であること
#
#    凍結する瞬間: JST 2026-08-03 00:30
#      = UTC 2026-08-02 15:30（9時間前なので日付が前日に落ちる）
#    大会は深夜まで動くため、この時間帯の操作は例外ではなく日常。
# ============================================================
print("\n[2] [A-2] 5_attendance.py: 深夜0:30の日付・時刻がJSTであること")

ATT = Path(ROOT, "pages", "5_attendance.py")
MIDNIGHT_JST = datetime(2026, 8, 3, 0, 30, tzinfo=JST)

expr_today = _find_assign_expr(ATT, "today_str")
_check("today_str の定義を見つけられた", expr_today is not None,
       "モジュールレベルの today_str = ... が見つからない（実装が変わった可能性）")

if expr_today:
    try:
        got_today = _eval_frozen(ATT, expr_today, MIDNIGHT_JST)
    except Exception as e:  # JST定数の定義方法が想定外だとここに来る
        got_today = f"<評価エラー: {e}>"
    # 期待値の根拠: JST 2026-08-03 00:30 の「今日」は 2026-08-03。
    # naive 実装だと UTC 2026-08-02 15:30 → "2026-08-02"（前日）になる。
    _check(
        "today_str が JST の日付 2026-08-03（UTCの前日 2026-08-02 ではない）",
        got_today == "2026-08-03",
        f"got {got_today!r} / expr={expr_today}",
    )

expr_now = _find_assign_expr(ATT, "now_str")
_check("now_str の定義を見つけられた", expr_now is not None,
       "モジュールレベルの now_str = ... が見つからない（実装が変わった可能性）")

if expr_now:
    try:
        got_now = _eval_frozen(ATT, expr_now, MIDNIGHT_JST)
    except Exception as e:
        got_now = f"<評価エラー: {e}>"
    # 期待値の根拠: JST 00:30 → "00:30"。naive 実装は UTC 15:30 → "15:30"。
    # now_str は `planned_start <= now_str` の比較に使われる（5_attendance.py の一括出勤）。
    # "15:30" になると 15:30以前の予定者しか拾えず、深夜シフトが一括出勤から漏れる。
    _check(
        "now_str が JST の時刻 00:30（UTCの 15:30 ではない）",
        got_now == "00:30",
        f"got {got_now!r} / expr={expr_now}",
    )


# ============================================================
# 3. [A-3] 凍結退勤の既定「退勤時刻（時）」が JST であること
#
#    凍結する瞬間: JST 2026-08-03 01:00（イベント運用上の 8/2 25:00）
#      = UTC 2026-08-02 16:00
#    naive 実装だと既定値が 16 になる。18:00 出勤のシフトに対して
#    16:00 退勤を保存すると end - start が負 → utils/calculator.py:112 の
#    `if total <= 0: return ShiftHours(0, 0, 0, ...)` で全部0 → 基本給 ¥0。
#
#    ※ 補足（このテストの対象外）:
#      number_input は max_value=29 なので、本来は 25 を既定にするのが
#      イベント日の運用に沿う。ただしそれは「24時超え表記の扱い」という別の論点で、
#      タイムゾーン欠陥とは切り分ける。ここは「JSTの時刻になっているか」だけを見る。
# ============================================================
print("\n[3] [A-3] 5_attendance.py: 凍結退勤の既定時刻がJSTであること")

LATE_NIGHT_JST = datetime(2026, 8, 3, 1, 0, tzinfo=JST)
expr_freeze = _find_widget_kwarg(ATT, "退勤時刻（時）", "value")
_check("凍結退勤の number_input(value=...) を見つけられた", expr_freeze is not None,
       'st.number_input("退勤時刻（時）", ..., value=...) が見つからない')

if expr_freeze:
    try:
        got_freeze = _eval_frozen(ATT, expr_freeze, LATE_NIGHT_JST)
    except Exception as e:
        got_freeze = f"<評価エラー: {e}>"
    # 期待値の根拠: JST 01:00 の「時」は 1。naive 実装は UTC 16:00 → 16。
    _check(
        "凍結退勤の既定時刻が JST の 1 時（UTCの 16 時ではない）",
        got_freeze == 1,
        f"got {got_freeze!r} / expr={expr_freeze} — "
        "16 だと 18:00出勤より前の退勤になり勤務時間が負→基本給¥0",
    )

    # 金額事故そのものを再現する。既定値をそのまま採用したときに
    # 18:00〜25:00 のシフトが ¥0 にならないことを、実際の計算エンジンで確かめる。
    # 計算エンジン側が壊れている（構文エラー等）ときに本テストごと落ちると
    # タイムゾーンの検査結果が読めなくなるので、import 失敗も1件の失敗として扱う。
    try:
        from utils.calculator import (
            calculate_shift_hours, calculate_daily_pay, parse_time_to_minutes,
        )
        _calc_err = None
    except Exception as e:
        _calc_err = e
    _check("utils.calculator を import できる", _calc_err is None,
           f"{type(_calc_err).__name__}: {_calc_err}")

    if _calc_err is None and isinstance(got_freeze, int):
        start_min = parse_time_to_minutes("18:00")          # 1080分
        end_min = parse_time_to_minutes(f"{got_freeze:02d}:00")
        sh = calculate_shift_hours(start_min, end_min, "2026-08-02",
                                   break_6h=0, break_8h=0)  # Pacific運用は休憩控除なし
        pay = calculate_daily_pay(sh, hourly_rate=1500, night_rate=1875,
                                  transport=0, role="Dealer")
        # 期待値の根拠:
        #   既定値が UTC の 16 → 16:00 < 18:00 なので total = 960-1080 = -120分 → 全項目0 → base_pay 0円
        #   JST の 1 なら 1:00 も 18:00 より前なので同じく0になる。
        #   つまり「既定値をそのまま押すと¥0」という事故は、時刻が JST でも
        #   24時超え表記（25:00）を採らないかぎり残る。
        #   ここでは「UTC由来の16が入っていない」ことを金額側からも押さえる。
        _check(
            "既定値が UTC 由来の 16 時ではない（16時だと 18:00出勤の基本給が ¥0）",
            got_freeze != 16,
            f"freeze_hour={got_freeze} → 勤務 {sh.total_minutes}分 / 基本給 ¥{pay.base_pay}",
        )


# ============================================================
# 4. [B] コンテナのタイムゾーン設定
#
#    python:3.12-slim は TZ を設定しなければ UTC で動く。
#    アプリ側を全部 tz付きにするのが本筋だが、コンテナ側も JST に揃えておかないと
#    ・ログの時刻が9時間ずれて障害調査が狂う
#    ・今後うっかり naive な now() が入り込んだときに即事故になる
#    ため、二重の防御としてここも検査する。
# ============================================================
print("\n[4] [B] Dockerfile / entrypoint に TZ=Asia/Tokyo 相当の設定があること")

DOCKERFILE = Path(ROOT, "Dockerfile")
ENTRYPOINT = Path(ROOT, "deploy", "entrypoint.sh")

_check("Dockerfile が存在する", DOCKERFILE.exists(), str(DOCKERFILE))
_check("deploy/entrypoint.sh が存在する", ENTRYPOINT.exists(), str(ENTRYPOINT))

deploy_sources = {}
for p in (DOCKERFILE, ENTRYPOINT, Path(ROOT, "railway.json")):
    if p.exists():
        deploy_sources[p.name] = _read(p)

# ENV TZ=Asia/Tokyo / ENV TZ Asia/Tokyo / export TZ="Asia/Tokyo" のいずれも認める
_TZ_RE = re.compile(r'\bTZ\s*[=\s]\s*["\']?Asia/Tokyo')
tz_hits = [name for name, src in deploy_sources.items() if _TZ_RE.search(src)]
_check(
    "TZ=Asia/Tokyo が Dockerfile か entrypoint に設定されている",
    bool(tz_hits),
    "設定なし＝コンテナは UTC で動く。検査したファイル: "
    + ", ".join(deploy_sources) ,
)

# TZ を設定しても zoneinfo のデータが無ければ黙って UTC に戻る（＝設定した気になるのが一番危ない）。
# 担保の方法は2つあり、どちらかを満たしていればよい:
#   ① イメージに tzdata を入れる（/usr/share/zoneinfo/Asia/Tokyo が引ける）
#   ② アプリ側が固定オフセット timezone(timedelta(hours=9)) を使う（zoneinfo不要）
docker_src = deploy_sources.get("Dockerfile", "")
has_tzdata = bool(re.search(r"\btzdata\b", docker_src)) or \
    bool(re.search(r"zoneinfo/Asia/Tokyo", docker_src))
uses_fixed_offset = not all_offenders and bool(
    re.search(r"timezone\(\s*timedelta\(\s*hours\s*=\s*9",
              "\n".join(_read(p) for p in page_files))
)
_check(
    "TZ が実際に解決できる担保がある（tzdata導入 または 固定オフセットJST実装）",
    has_tzdata or uses_fixed_offset,
    f"tzdata={has_tzdata} / 固定オフセットJST={uses_fixed_offset} — "
    "zoneinfo が無い環境で TZ=Asia/Tokyo だけ設定すると黙って UTC のままになる",
)


# ============================================================
# 5. [C] 正しく実装されている側の回帰防止
#
#    10_pit_terminal.py と admin_guard.py は既に JST 実装。
#    今後の改修でここが naive に戻らないよう固定する。
# ============================================================
print("\n[5] [C] 既にJST実装の箇所を固定（回帰防止）")

PIT = Path(ROOT, "pages", "10_pit_terminal.py")
GUARD = Path(ROOT, "utils", "admin_guard.py")

for label, path in (("pages/10_pit_terminal.py", PIT), ("utils/admin_guard.py", GUARD)):
    _check(f"{label} が存在する", path.exists(), str(path))
    if not path.exists():
        continue

    _check(f"{label}: naive な現在時刻取得が無い",
           not _naive_now_calls(path),
           "naive: " + ", ".join(f"L{ln} {s}" for ln, s in _naive_now_calls(path)))

    expr_jst = _find_assign_expr(path, "_JST")
    _check(f"{label}: _JST 定数が定義されている", expr_jst is not None,
           "_JST = timezone(timedelta(hours=9)) が見つからない")
    if expr_jst:
        try:
            tz_obj = eval(expr_jst, _module_namespace(path))
            offset = tz_obj.utcoffset(datetime(2026, 8, 2, 12, 0))
        except Exception as e:
            offset = f"<評価エラー: {e}>"
        # 期待値の根拠: JST は UTC+9 の固定オフセット（日本に夏時間は無い）。
        _check(f"{label}: _JST のオフセットが UTC+9",
               offset == timedelta(hours=9),
               f"got {offset!r} / expr={expr_jst}")

# 機能テスト: OSのTZがUTCでも db._now() は JST の壁時計を返すこと。
# db._now() はDBへ保存する日時の唯一の生成点（db.py:119）なので、
# ここがずれると監査ログ・支払い履歴の時刻が全部9時間ずれる。
print("\n[5-2] db._now() は OS の TZ に依存しない")
_orig_tz = os.environ.get("TZ")
try:
    os.environ["TZ"] = "UTC"
    time.tzset()  # 本番コンテナ（TZ未設定＝UTC）と同じ状態を作る
    got_db_now = db._now()
    expected_dt = datetime.now(JST)
    parsed = datetime.strptime(got_db_now, "%Y-%m-%d %H:%M:%S")
    # 期待値の根拠: 実行の一瞬のずれを許容して差3秒以内。
    # naive 実装なら UTC を返すので差は約32400秒（9時間）になり、確実に落ちる。
    delta = abs((parsed - expected_dt.replace(tzinfo=None)).total_seconds())
    _check("db._now() が JST を返す（OSのTZ=UTCでも9時間ずれない）",
           delta < 3,
           f"got {got_db_now} / JST期待 {expected_dt:%Y-%m-%d %H:%M:%S} / 差 {delta:.0f}秒")
finally:
    if _orig_tz is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = _orig_tz
    time.tzset()


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
